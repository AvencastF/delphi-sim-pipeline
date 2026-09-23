// Generator-only companion to generate.cpp: same successful-event loop, no event files.
#include "Pythia8/Pythia.h"
#include <fstream>
#include <iomanip>
#include <iostream>
int main(int argc, char** argv) {
  if (argc != 3) return 2;
  const int requested = std::stoi(argv[2]);
  if (requested < 1 || requested > 10000000) return 2;
  Pythia8::Pythia pythia;
  if (!pythia.readFile(argv[1]) || !pythia.init()) return 3;
  pythia.settings.writeFile("resolved-settings.cmnd", true);
  int generated=0, attempts=0;
  double sumw=0, sumw2=0;
  while (generated < requested && attempts < requested*3) {
    ++attempts;
    if (!pythia.next()) continue;
    ++generated;
    double w=pythia.info.weight(); sumw+=w; sumw2+=w*w;
  }
  pythia.stat();
  std::ofstream out("generation.json");
  out << std::setprecision(17) << "{\"generated\":" << generated
      << ",\"attempts\":" << attempts << ",\"trials\":" << pythia.info.nTried()
      << ",\"sumw\":" << sumw << ",\"sumw2\":" << sumw2
      << ",\"sigma_pb\":" << pythia.info.sigmaGen()*1e9
      << ",\"sigma_error_pb\":" << pythia.info.sigmaErr()*1e9 << "}\n";
  return generated == requested && out.good() ? 0 : 5;
}
