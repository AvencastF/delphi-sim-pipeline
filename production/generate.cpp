// Fixed successful-event target; preserve weights and generator integration uncertainty.
// Avoid closure_gen's accepted-event target and native zero-vertex FADGEN writer.
#include "Pythia8/Pythia.h"
#include "Pythia8Plugins/HepMC3.h"
#include "HepMC3/WriterAscii.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc, char** argv) {
  if (argc != 3) { std::cerr << "usage: generate CARD COUNT\n"; return 2; }
  const int requested = std::stoi(argv[2]);
  if (requested <= 0 || requested > 10000000) return 2;
  Pythia8::Pythia pythia;
  if (!pythia.readFile(argv[1]) || !pythia.init()) return 3;
  pythia.settings.writeFile("resolved-settings.cmnd", true);
  pythia.particleData.list(15);
  pythia.particleData.list(23);
  Pythia8::Pythia8ToHepMC bridge;
  HepMC3::WriterAscii output("events.hepmc3");
  std::ofstream weights("event-weights.csv");
  weights << "fadgen_record,hepmc_event,weight\n" << std::setprecision(17);
  int generated = 0, attempts = 0;
  double sumw = 0, sumw2 = 0;
  while (generated < requested && attempts < requested * 3) {
    ++attempts;
    if (!pythia.next()) continue;
    HepMC3::GenEvent event(HepMC3::Units::GEV, HepMC3::Units::MM);
    bridge.fill_next_event(pythia, &event);
    event.set_event_number(generated + 1);
    output.write_event(event);
    if (output.failed()) return 4;
    ++generated;
    const double w = pythia.info.weight();
    sumw += w; sumw2 += w*w;
    weights << generated << ',' << event.event_number() << ',' << w << '\n';
  }
  output.close();
  pythia.stat();
  std::ofstream summary("generation.json");
  summary << std::setprecision(17)
          << "{\"requested\":" << requested << ",\"generated\":" << generated
          << ",\"attempts\":" << attempts << ",\"sumw\":" << sumw
          << ",\"sumw2\":" << sumw2
          << ",\"sigma_mb\":" << pythia.info.sigmaGen()
          << ",\"sigma_error_mb\":" << pythia.info.sigmaErr() << "}\n";
  return generated == requested && weights.good() && summary.good() ? 0 : 5;
}
