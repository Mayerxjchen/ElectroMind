/** CP2K / VASP / LAMMPS output parser.
 *
 * Extracts key metrics from computational chemistry output files:
 * - CP2K: energy, forces, SCF convergence, MD steps
 * - LAMMPS: thermo data (T, P, Etot, Volume)
 * - DeepMD: training loss curves (lcurve.out)
 * - VASP: OSZICAR energy, convergence
 */

import type { DeepMDLoss, EnergyPoint, MDStep, SCFCycle } from "../react/components/ScientificResults";

// ── CP2K output parser ───────────────────────────────────────────────

export function parseCP2KOutput(text: string): {
  energies: EnergyPoint[];
  scfCycles: SCFCycle[];
  mdSteps: MDStep[];
} {
  const energies: EnergyPoint[] = [];
  const scfCycles: SCFCycle[] = [];
  const mdSteps: MDStep[] = [];

  const lines = text.split("\n");
  let step = 0;
  let currentScf: SCFCycle[] = [];
  let inScf = false;

  for (const line of lines) {
    // Energy: "ENERGY| Total FORCE_EVAL ( QS ) energy [Hartree]  -17.1234567893"
    //          (旧格式 "energy (a.u.):" 亦兼容)
    const energyMatch = line.match(
      /ENERGY\|\s*Total FORCE_EVAL\s*\(.*?\)\s+energy\s*(?:\[[^\]]+\]|\(a\.u\.\)):?\s+([-\d.]+)/
    );
    if (energyMatch) {
      const scfMatch = line.match(/OT\s+(\d+)/) || line.match(/(\d+)\s+OT/);
      const converged = line.includes("converged") || !line.includes("NOT converged");
      energies.push({
        step: step++,
        energy: parseFloat(energyMatch[1]),
        scfSteps: scfMatch ? parseInt(scfMatch[1], 10) : undefined,
        converged,
        deltaE: energies.length > 0
          ? Math.abs(parseFloat(energyMatch[1]) - energies[energies.length - 1].energy)
          : undefined,
      });
    }

    // SCF iteration: "     1 OT CG       0.15E+02    1.5      -17.1234567890     -1.23E-02"
    const scfMatch = line.match(
      /^\s+(\d+)\s+(?:OT|DIIS)\s+\S+\s+[\d.]+\s+[\d.]+\s+([-\d.]+)\s+([-\d.Ee+-]+)/
    );
    if (scfMatch) {
      if (!inScf) {
        currentScf = [];
        inScf = true;
      }
      currentScf.push({
        iteration: parseInt(scfMatch[1], 10),
        energy: parseFloat(scfMatch[2]),
        deltaE: parseFloat(scfMatch[3]),
      });
    } else if (inScf && line.trim() === "") {
      inScf = false;
      // Keep only the last SCF cycle
      scfCycles.length = 0;
      scfCycles.push(...currentScf);
    }

    // MD step: "MD| Step number:"
    const mdMatch = line.match(/MD\|\s*Step number:\s+(\d+)/);
    if (mdMatch) {
      // TODO: extract T, P, Etot from surrounding lines
    }
  }

  return { energies, scfCycles, mdSteps };
}

// ── LAMMPS thermo parser ─────────────────────────────────────────────

export function parseLAMMPSThermo(text: string): MDStep[] {
  const steps: MDStep[] = [];
  const lines = text.split("\n");

  let headerIdx = -1;
  const headers: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith("Step") && line.includes("Temp") && line.includes("Press")) {
      headerIdx = i;
      headers.length = 0;
      headers.push(...line.split(/\s+/).map((h) => h.trim().toLowerCase()));
      continue;
    }
    if (headerIdx >= 0 && i > headerIdx && /^\d/.test(line)) {
      const parts = line.split(/\s+/);
      if (parts.length < 2) continue;

      const get = (name: string): number => {
        const idx = headers.indexOf(name.toLowerCase());
        return idx >= 0 && idx < parts.length ? parseFloat(parts[idx]) : 0;
      };

      steps.push({
        step: parseInt(parts[0], 10),
        timeFs: get("time") || (parseInt(parts[0]) * 0.5), // default 0.5 fs timestep
        temperature: get("temp"),
        pressure: get("press") * 0.0001 || get("press"), // atm → bar approx
        etot: get("toteng") || get("etot"),
        ekin: get("kineng") || get("ekin"),
        epot: get("poteng") || get("epot"),
        volume: get("volume") || get("vol"),
      });
    }
  }

  return steps;
}

// ── DeepMD lcurve.out parser ─────────────────────────────────────────

export function parseDeepMDLoss(text: string): DeepMDLoss[] {
  const points: DeepMDLoss[] = [];
  const lines = text.split("\n");

  // lcurve.out format: # step  loss  l2_energy  l2_force
  for (const line of lines) {
    if (line.startsWith("#")) continue;
    const parts = line.trim().split(/\s+/);
    if (parts.length < 2) continue;
    const step = parseInt(parts[0], 10);
    if (isNaN(step)) continue;

    points.push({
      step,
      loss: parseFloat(parts[1]),
      l2Energy: parts.length > 2 ? parseFloat(parts[2]) : undefined,
      l2Force: parts.length > 3 ? parseFloat(parts[3]) : undefined,
    });
  }

  return points;
}

// ── VASP OSZICAR parser ──────────────────────────────────────────────

export function parseVASPOSZICAR(text: string): EnergyPoint[] {
  const energies: EnergyPoint[] = [];
  const lines = text.split("\n");

  for (const line of lines) {
    // OSZICAR energy line: "  1 F= -.17123456E+02 E0= -.17123456E+02  d E =-.171235E+02"
    const match = line.match(/^\s*(\d+)\s+F=\s+([-\d.Ee+-]+)/);
    if (!match) continue;

    const step = parseInt(match[1], 10);
    const energy = parseFloat(match[2]);
    const prev = energies[energies.length - 1];

    energies.push({
      step,
      energy,
      deltaE: prev ? Math.abs(energy - prev.energy) : undefined,
      converged: true, // OSZICAR only records converged steps
    });
  }

  return energies;
}
