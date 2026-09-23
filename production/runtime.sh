#!/bin/bash
# Fresh subprocess per stage; node runtime supplies isolated cached environments.
set -eo pipefail
stage=$1
case "$stage" in
 generate)
  if [ "${LONG_STAGE_ENV_READY:-}" != "$stage" ]; then
    source /cvmfs/sw.hsf.org/key4hep/setup.sh -r 2026-04-08
  fi
  /build/generate card.cmnd "$2"
  ;;
 bhwide)
  if [ "${LONG_STAGE_ENV_READY:-}" != "$stage" ]; then
    source /cvmfs/sw.hsf.org/key4hep/setup.sh -r 2026-04-08
  fi
  python3 /sim/production/bhwide.py "$2" "$3"
  ;;
 whizard)
  if [ "${LONG_STAGE_ENV_READY:-}" != "$stage" ]; then
    source /cvmfs/sw.hsf.org/key4hep/setup.sh -r 2026-04-08
  fi
  whizard card.sin
  ;;
 fadgen)
  /build/hepmc2fadgen events.hepmc3 my_events.fadgen
  ;;
 simulate)
  export DELPHI_INSTALL_DIR=/delphi
  if [ "${LONG_STAGE_ENV_READY:-}" != "$stage" ]; then source /delphi/setup.sh; fi
  cp /delphi/releases/almalinux-9-x86_64/latest/simana/v94c/dat/longdst.des longdst.des
  runsim -VERSION v94c -LABO CERN -NRUN "$2" -EBEAM "$3" -NEVMAX "$4" -gext my_events.fadgen -STITL simulation.title -LONG
  test -s simana.ldst
  ;;
 convert)
  bash /edm/scripts/production/convert.sh /build/converter/delphi_sdst_pass simana.ldst events.edm4hep.root audit
  ;;
 *) echo "Unknown stage $stage" >&2; exit 2;;
esac
