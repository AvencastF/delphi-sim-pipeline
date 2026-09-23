# BHWIDE standalone diagnostic adapter

Prepared 2026-09-23. NOT yet compiled or run; not a production generator.

Source: Belle II mirror of BHWIDE **1.05**, pinned to basf2 revision
442ac586c1b4e308b13e1bb7ec4ff720163127ae. `fetch_sources.py <new-directory>`
downloads twelve upstream Fortran files and records SHA256 hashes; it executes
nothing. Preserve authors' notices; cite Jadach, Placzek and Ward,
Phys. Lett. B390 (1997) 298, https://arxiv.org/abs/hep-ph/9608412.
This mirror is not the newer BHWIDE 1.07 advertised upstream.

The Belle II copy delegates random numbers to its caller. `rng.cc` supplies
mt19937_64 with a specified seed and open-interval double uniforms. This is an
explicit adapter choice, not a claim to reproduce the original RANMAR stream.
Upstream physics routines are unmodified.

`driver.f90` generates a FIXED number of trials with variable weights; rejected
zero-weight trials count in normalization but are not exported as particles
(BHWIDE clears their momenta). It writes all photons and the full e+/e- state,
flipping z so the incoming electron is along +z. Record event identity is the
trial number, so gaps are expected and are not detector losses. XPAR(10) is pb;
XPAR(11) is the RELATIVE statistical uncertainty. Preserve the crude cross
section XPAR(20), trial count and principal WTMOD weights to check normalization.

`diagnostic.dat` is a comparison proposal, not approved nominal physics:
Z on; s+t+interference; weighted; EW corrections with ALIBABA; CALKUL radiation;
Burkhardt/Pietrzyk vacuum polarization; 91.202 GeV; both scattering angles
5–175 degrees; both final energies >1 GeV; acollinearity <180 degrees.
EPSCMS=1e-5 and WTMAX=3; the latter is unused for weighted generation.
The five EW inputs 91.1882, 2.4952, 0.22225, 174.3, 115 are the historical
Belle II wrapper defaults, retained explicitly for a first software diagnostic,
not selected as this project's nominal EW scheme. ALIBABA may recompute width
and weak angle; record the printed effective parameters. Input angles are
relative to each particle's incoming beam. The symmetric range avoids a
charge-convention ambiguity but does not certify small-angle precision.

Build and generate only on an approved NERSC compute allocation, with key4hep
sourced INSIDE the existing image. No DELSIM or conversion is wired into this
adapter until normalized output and radiation/kinematics have passed checks.
