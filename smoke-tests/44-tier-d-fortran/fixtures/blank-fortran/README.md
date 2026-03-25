# blank-fortran — WRF Atmospheric Model HPC Job (Fortran 90)

## What this program does

`wrf_model.f90` is a Fortran 90 program that implements a 72-hour CONUS-3km
weather forecast simulation (Weather Research and Forecasting model, WRF 4.5):

1. **domain_init** — allocates 3D state arrays (U, V, W, T, P, QV, QC, QR)
   for the CONUS-3km grid (1,500,000 grid points, 50 vertical levels)
2. **read_wrfinput** — reads initial conditions from the `wrfinput_d01` NetCDF4
   file (temperature, wind, moisture fields)
3. **time_integration_chunk** — iterates over 14,400 timesteps (18s each,
   72h forecast), running Runge-Kutta 3rd-order dynamics and calling physics
   parameterisation subroutines:
   - **microphysics** (Thompson scheme)
   - **boundary_layer** (YSU scheme)
   - **surface_layer** (MM5 scheme)
   - **radiation_sw / radiation_lw** (RRTMG)
   - **cumulus** (Kain-Fritsch)
4. **mpi_halo_exchange** — exchanges boundary data between 64 MPI ranks via
   `MPI_Sendrecv` after each timestep
5. **write_history_files** — writes NetCDF4 output files every 3 forecast
   hours (24 output files total)

## Why it has no observability

This is a **Tier D** legacy HPC application. Fortran has no OpenTelemetry SDK.
The Fortran runtime on HPC clusters cannot load OTel agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`WRITE(*,...)` statements to stdout and MPI rank 0 logging.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `wrf_model.f90` to add `SYSTEM` calls invoking `curl` (available
   on the HPC compute nodes) to POST spans to the sidecar for each major step
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
