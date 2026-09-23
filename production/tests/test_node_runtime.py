import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import campaign as c
import node_runtime as n


def claim_all(root,tasks):
    while n.claim_next(Path(root),tasks,0,10000,{'rank':os.getpid()}) is not None:
        pass


class TestNodeRuntime(unittest.TestCase):
    def test_node_pool_reuses_workers_and_writes_runtime_record(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ('claims','results','logs'):(root/name).mkdir()
            tasks=[{'id':str(i),'estimated_seconds':1} for i in range(12)]
            c.write(root/'plan.json',{'site':{},'tasks':tasks,'fleet_jobs':[{'task_ids':[t['id'] for t in tasks],'workers_per_node':4}]})
            def fake_task(directory,task):
                c.write(directory/'results'/(task['id']+'.json'),{'worker':os.getpid()})
            with patch.object(c,'compute'),patch.object(n,'environments',return_value={}),patch.object(n,'physical_cores',return_value=[[0],[1],[2],[3]]),patch.object(os,'sched_getaffinity',return_value={0,1,2,3},create=True),patch.object(os,'sched_setaffinity',create=True),patch.object(c,'run_task',side_effect=fake_task),patch.dict(os.environ,{'SLURM_JOB_ID':'1','SLURM_PROCID':'0','FLEET_JOB_INDEX':'0'}):
                n.inside(root,4)
            self.assertEqual(len(list((root/'results').glob('*.json'))),12)
            record=c.read(root/'logs/node-0-0.json')
            self.assertEqual(record['worker_exit_codes'],[0,0,0,0])
            self.assertEqual(record['container_launches'],1)
            self.assertLessEqual(len({c.read(p)['worker'] for p in (root/'results').glob('*.json')}),4)

    def test_concurrent_queue_exactly_once_and_no_retry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'claims').mkdir();(root/'results').mkdir()
            tasks=[{'id':str(i),'estimated_seconds':1} for i in range(1024)]
            (root/'claims/0').mkdir();(root/'claims/0/failure.json').write_text('{}')
            (root/'results/1.json').write_text('{}')
            ctx=multiprocessing.get_context('fork')
            workers=[ctx.Process(target=claim_all,args=(d,tasks)) for _ in range(4)]
            for worker in workers:worker.start()
            for worker in workers:worker.join(10);self.assertEqual(worker.exitcode,0)
            owners=list((root/'claims').glob('*/owner.json'))
            self.assertEqual(len(owners),1022)
            self.assertEqual({p.parent.name for p in owners},set(str(i) for i in range(2,1024)))
            # Rewinding a lost cursor cannot repeat a claimed or completed task.
            (root/'claims/queue-0.cursor').write_text('0')
            self.assertIsNone(n.claim_next(root,tasks,0,10000,{}))

    def test_cursor_replaced_without_mutating_old_readers_and_lock_stays_stable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'claims').mkdir();(root/'results').mkdir()
            tasks=[{'id':str(i),'estimated_seconds':1} for i in range(3)]
            n.claim_next(root,tasks,0,10000,{})
            cursor=root/'claims/queue-0.cursor';lock=cursor.with_suffix('.lock')
            lock_inode=lock.stat().st_ino
            with cursor.open() as old:
                n.claim_next(root,tasks,0,10000,{})
                self.assertEqual(old.read().strip(),'1')
                self.assertEqual(cursor.read_text().strip(),'2')
            self.assertEqual(lock.stat().st_ino,lock_inode)

    def test_interrupted_cursor_replace_does_not_replay_claim(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'claims').mkdir();(root/'results').mkdir()
            tasks=[{'id':str(i),'estimated_seconds':1} for i in range(2)]
            replace=os.replace
            def fail_cursor(src,dst):
                if Path(dst).suffix=='.cursor':raise OSError('interrupted replace')
                return replace(src,dst)
            with patch.object(os,'replace',side_effect=fail_cursor):
                with self.assertRaisesRegex(OSError,'interrupted replace'):
                    n.claim_next(root,tasks,0,10000,{})
            self.assertEqual(n.claim_next(root,tasks,0,10000,{})['id'],'1')
            self.assertIsNone(n.claim_next(root,tasks,0,10000,{}))

    def test_corrupt_cursor_fails_without_claiming_more_work(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'claims').mkdir();(root/'results').mkdir()
            (root/'claims/queue-0.cursor').write_bytes(b'\x00\x00\x00549')
            with self.assertRaises(ValueError):
                n.claim_next(root,[{'id':'0'}],0,10000,{})
            self.assertFalse((root/'claims/0').exists())

    def test_core_groups_respect_allocation_and_smt(self):
        with tempfile.TemporaryDirectory() as d:
            topology=Path(d)
            for cpu,socket,core in [(0,0,0),(128,0,0),(1,0,1),(129,0,1),(64,1,0)]:
                p=topology/('cpu'+str(cpu))/'topology';p.mkdir(parents=True)
                (p/'physical_package_id').write_text(str(socket));(p/'core_id').write_text(str(core))
            self.assertEqual(n.physical_cores({0,128,1,64},topology),[[0,128],[1],[64]])

    def test_clean_environment_snapshots_do_not_leak(self):
        base={'PATH':os.environ['PATH'],'BASE_VALUE':'yes'}
        modern=n.capture_environment('export MODERN_ONLY=1',base)
        legacy=n.capture_environment('export LEGACY_ONLY=1',base)
        self.assertNotIn('MODERN_ONLY',legacy);self.assertNotIn('LEGACY_ONLY',modern)
        self.assertNotIn('MODERN_ONLY',base)

    def test_node_command_has_one_container_and_bounded_mounts(self):
        with patch.dict(os.environ,{'SLURM_JOB_ID':'1','SLURM_PROCID':'0','FLEET_JOB_INDEX':'0'}),patch.object(os,'sched_getaffinity',return_value={0,128},create=True),patch.object(n.socket,'gethostname',return_value='nid123'):
            cmd=n.container_command(Path('/scratch/test'),{'site':{'build_root':'/scratch/build','image':'image@sha256:abc'}},1)
            self.assertEqual(cmd.count('podman-hpc'),1)
            self.assertIn('--network=none',cmd);self.assertIn('--cpuset-cpus=0,128',cmd)
            self.assertIn('/scratch/test:/scratch/test:ro',cmd)
            self.assertIn('/scratch/test/work:/scratch/test/work:rw',cmd)
            self.assertEqual(cmd[-4:],['/sim/production/node_runtime.py','inside','/scratch/test','1'])

    def test_stages_inside_node_never_launch_nested_container(self):
        with patch.object(c,'NODE_ENVIRONMENTS',{}),patch.object(c,'CACHED_PLAN',{'site':{'build_root':'/build'}}):
            command=c.command(Path('/campaign'),{'id':'one'},'simulate',[123,45.601,18])
        self.assertEqual(command[:4],['/bin/bash','--noprofile','--norc','/sim/production/runtime.sh'])
        self.assertNotIn('podman-hpc',command)

    def test_stage_runs_in_own_directory_and_cached_environment(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work/one';work.mkdir(parents=True);(work/'tmp').mkdir();(root/'logs').mkdir()
            site={'stage_timeout_seconds':10};env={'PATH':os.environ['PATH'],'STAGE_VALUE':'isolated'}
            cmd=[sys.executable,'-c',"import os,pathlib;pathlib.Path('seen').write_text(os.environ['STAGE_VALUE'])"]
            with patch.object(c,'NODE_ENVIRONMENTS',{'generate':env}),patch.object(c,'CACHED_PLAN',{'site':site}),patch.object(c,'command',return_value=cmd),patch.dict(os.environ,{'SLURM_PROCID':'0'}):
                c.stage_run(root,{'id':'one'},'generate',[])
            self.assertEqual((work/'seen').read_text(),'isolated')
            self.assertNotIn('LONG_STAGE_ENV_READY',env)

    def test_timeout_does_not_stop_node_or_other_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work/one';work.mkdir(parents=True);(work/'tmp').mkdir();(root/'logs').mkdir()
            unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
            try:
                with patch.object(c,'NODE_ENVIRONMENTS',{'generate':dict(os.environ)}),patch.object(c,'CACHED_PLAN',{'site':{'stage_timeout_seconds':1}}),patch.object(c,'command',return_value=[sys.executable,'-c','import time;time.sleep(30)']),patch.dict(os.environ,{'SLURM_PROCID':'0'}):
                    with self.assertRaisesRegex(RuntimeError,'failed \\(124\\)'):
                        c.stage_run(root,{'id':'one'},'generate',[])
                self.assertIsNone(unrelated.poll())
                self.assertEqual(c.read(work/'generate-resource.json')['exit_code'],124)
            finally:
                unrelated.terminate();unrelated.wait()


if __name__=='__main__':unittest.main()
