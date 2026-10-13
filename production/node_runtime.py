#!/usr/bin/env python3
"""One container per node, isolated stage environments, one shared chunk queue."""
import fcntl
import multiprocessing
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time

import campaign as c


def container_command(root, plan, workers):
    site = plan['site']
    host = socket.gethostname()
    cpus = ','.join(str(n) for n in sorted(os.sched_getaffinity(0)))
    cmd = ['podman-hpc', 'run', '--rm', '--network=none', '--init',
           '--name', 'long-{}-node-{}'.format(os.environ['SLURM_JOB_ID'], host)+(('-'+root.parent.name) if site.get('detector_validation') else ''),
           '--hostname', host, '--cpuset-cpus='+cpus, '--entrypoint', '/usr/bin/python3',
           '-v', '/cvmfs:/cvmfs:ro', '-v', str(root)+':'+str(root)+':ro',
           '-v', str(root/'source/sim')+':/sim:ro',
           '-v', str(root/'source/edm')+':/edm:ro',
           '-v', site['build_root']+':/build:ro',
           '-v', str(root/'source/sim/production/no-eos.sh')+':/delphi/env/mount_eos.sh:ro']
    if site.get('bhwide_build_root'):
        cmd += ['-v', site['bhwide_build_root']+':/bhwide:ro']
    for name in ('work', 'logs', 'claims', 'results'):
        cmd += ['-v', str(root/name)+':'+str(root/name)+':rw']
    for name in ('SLURM_JOB_ID', 'SLURM_JOB_END_TIME', 'SLURM_PROCID', 'FLEET_JOB_INDEX'):
        if name in os.environ:
            cmd += ['-e', name+'='+os.environ[name]]
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        cmd += ['-e', name+'=1']
    return cmd+[site['image'], '/sim/production/node_runtime.py', 'inside', str(root), str(workers)]


def launch(root, workers):
    c.compute()
    plan = c.read(root/'plan.json')
    c.verify_inputs(root, plan)  # Once per node, before any physics process starts.
    if workers < 1 or workers > 128:
        raise ValueError('Workers per node must be in [1,128]')
    command = container_command(root, plan, workers)
    os.execvp(command[0], command)


def physical_cores(allowed, topology=Path('/sys/devices/system/cpu')):
    groups = {}
    for cpu in sorted(allowed):
        path = topology/('cpu'+str(cpu))/'topology'
        key = ((path/'physical_package_id').read_text().strip(),
               (path/'core_id').read_text().strip())
        groups.setdefault(key, []).append(cpu)
    return list(groups.values())


def capture_environment(script, base):
    # Environment snapshots stay in memory; never write or print their contents.
    code = 'set -e\n'+script+'\n/usr/bin/env -0'
    raw = subprocess.check_output(['/bin/bash', '--noprofile', '--norc', '-c', code], env=base)
    return dict(item.decode().split('=', 1) for item in raw.split(b'\0') if item)


def environments(site):
    base = dict(os.environ)
    modern_setup = 'source /cvmfs/sw.hsf.org/key4hep/setup.sh -r '+shlex.quote(site['key4hep_release'])+' >/dev/null'
    legacy_setup = 'export DELPHI_INSTALL_DIR=/delphi\nsource /delphi/setup.sh >/dev/null'
    modern = capture_environment(modern_setup, base)
    legacy = capture_environment(legacy_setup, base)
    conversion = capture_environment(modern_setup+'\nunset CXXFLAGS CFLAGS LDFLAGS', legacy)
    conversion['DELPHI_CONVERTER_ENV_READY'] = '1'
    return {'generate':modern, 'whizard':modern, 'bhwide':modern, 'fadgen':base,
            'simulate':legacy, 'convert':conversion}


def claim_next(root, tasks, job_index, remaining, owner):
    # Lock a stable inode, then reopen the cursor and replace it atomically.
    # Append + truncate on a shared filesystem can leave NUL-filled holes.
    # Never lock the replaced cursor inode: waiters could lock an obsolete file.
    cursor = root/'claims'/('queue-'+str(job_index)+'.cursor')
    with cursor.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = cursor.read_text().strip() if cursor.exists() else ''
        index = int(value) if value else 0
        if not 0 <= index <= len(tasks):
            raise ValueError('Queue cursor outside task range: '+str(index))
        while index < len(tasks):
            task = tasks[index]
            index += 1
            if remaining < float(task.get('estimated_seconds', 120))+60:
                continue
            if (root/'results'/(task['id']+'.json')).exists():
                continue
            directory = root/'claims'/task['id']
            try:
                directory.mkdir()
            except FileExistsError:
                continue
            c.write(directory/'owner.json', dict(owner, start=time.time()))
            c.write(cursor, index)
            return task
        c.write(cursor, index)
    return None


def work(root, plan, tasks, job_index, rank, cpus, stage_envs):
    os.sched_setaffinity(0, set(cpus))
    os.environ['SLURM_PROCID'] = str(rank)
    c.NODE_ENVIRONMENTS = stage_envs
    c.CACHED_PLAN = plan
    owner = {'job':os.environ['SLURM_JOB_ID'], 'rank':rank,
             'host':socket.gethostname(), 'cpus':cpus}
    while c.remaining_seconds(plan['site']) >= 180:
        task = claim_next(root, tasks, job_index, c.remaining_seconds(plan['site']), owner)
        if task is None:
            return
        try:
            c.run_task(root, task)
        except Exception as error:
            c.write(root/'claims'/task['id']/'failure.json',
                    {'error':str(error), 'time':time.time()})


def inside(root, workers):
    c.compute()
    plan = c.read(root/'plan.json')
    job_index = int(os.environ['FLEET_JOB_INDEX'])
    job = plan['fleet_jobs'][job_index]
    if workers != job['workers_per_node']:
        raise ValueError('Worker count differs from frozen job')
    by_id = {task['id']:task for task in plan['tasks']}
    tasks = sorted((by_id[i] for i in job['task_ids']),
                   key=lambda task: (-task.get('estimated_seconds', 120), task['id']))
    cores = physical_cores(os.sched_getaffinity(0))
    if len(cores) < workers:
        raise ValueError('Allocation exposes fewer physical cores than requested workers')
    start = time.time()
    stage_envs = environments(plan['site'])
    context = multiprocessing.get_context('fork')
    node_rank = int(os.environ['SLURM_PROCID'])
    processes = [context.Process(target=work, args=(root, plan, tasks, job_index,
                 node_rank*workers+i, cores[i], stage_envs)) for i in range(workers)]
    record = {'host':socket.gethostname(), 'node_rank':node_rank,
              'workers':workers, 'physical_core_masks':cores[:workers],
              'environment_setup_seconds':time.time()-start, 'started':start,
              'container_launches':1, 'runtime':'one-container-per-node'}
    path = root/'logs'/('node-{}-{}.json'.format(job_index, node_rank))
    c.write(path, record)
    for process in processes:
        process.start()
    for process in processes:
        process.join()
    record.update(finished=time.time(), worker_exit_codes=[p.exitcode for p in processes])
    c.write(path, record)
    if any(p.exitcode for p in processes):
        raise RuntimeError('A node worker exited unexpectedly; retain its claimed chunks')


if __name__ == '__main__':
    action, directory, count = sys.argv[1:]
    if action not in ('launch', 'inside'):
        raise SystemExit('Expected launch or inside')
    (launch if action == 'launch' else inside)(Path(directory).resolve(), int(count))
