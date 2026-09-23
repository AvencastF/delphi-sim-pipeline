// Belle II's BHWIDE source delegates VARRAN/RANMAR to the caller.
// Explicit project RNG: mt19937_64, pinned seed, open interval (0,1).
#include <random>
#include <cstdint>
static std::mt19937_64 engine;
extern "C" void seed_rng_(const int* seed) { engine.seed(static_cast<uint64_t>(*seed)); }
static double draw() { return (static_cast<double>(engine() >> 12) + 0.5) * 0x1.0p-52; }
extern "C" void varran_(double* values, const int* count) {
  for (int i=0; i<*count; ++i) values[i]=draw();
}
extern "C" void ranmar_(double* value) { *value=draw(); }
