#!/bin/bash
# Execute only inside the pinned OCI image on allocated compute.
set -eo pipefail
: "${BUILD_DIR:?}" "${SIM_REPO:?}" "${EDM_REPO:?}"
export DELPHI_INSTALL_DIR=/delphi
source /delphi/setup.sh
source /cvmfs/sw.hsf.org/key4hep/setup.sh -r "${KEY4HEP_RELEASE:?}"
unset CXXFLAGS CFLAGS LDFLAGS
mkdir -p "$BUILD_DIR"
python3 - <<'PY'
import os,pathlib,shlex,subprocess
paths=':'.join(os.environ.get(k,'') for k in ('ROOT_INCLUDE_PATH','CPLUS_INCLUDE_PATH','CPATH')).split(':')
inc=next(pathlib.Path(p) for p in paths if (pathlib.Path(p)/'HepMC3/GenEvent.h').is_file())
lib=next(p for p in (inc.parent/'lib64',inc.parent/'lib') if (p/'libHepMC3.so').exists())
flags=shlex.split(subprocess.check_output(['pythia8-config','--cxxflags','--libs'],text=True))
base=['g++','-std=c++17','-O2',f'-I{inc}',f'-L{lib}',f'-Wl,-rpath,{lib}']
root=pathlib.Path(os.environ['SIM_REPO']);out=pathlib.Path(os.environ['BUILD_DIR'])
subprocess.run(base+[str(root/'production/generate.cpp'),'-o',str(out/'generate')]+flags+['-lHepMC3'],check=True)
subprocess.run(base+[str(root/'hepmc2fadgen.cpp'),'-o',str(out/'hepmc2fadgen'),'-lHepMC3'],check=True)
PY
cmake -S "$EDM_REPO/delphi_edm4hep" -B "$BUILD_DIR/converter" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR/converter" -j "${BUILD_CPUS:-4}"
pythia8-config --version
whizard --version || true

