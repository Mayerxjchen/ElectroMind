/** Scientific file recognizer — identifies file types and extracts summaries.
 *
 * Maps file extensions and content signatures to renderers:
 * - .xyz, .pdb, .cif → StructureViewer
 * - CP2K *.out, *.log → ScientificResults (energy + SCF)
 * - LAMMPS log.lammps, thermo.* → MD trajectory
 * - DeepMD lcurve.out → loss curve
 * - VASP OSZICAR, OUTCAR → energy table
 * - .cub, .cube, .chg → "外部可视化推荐"
 */

import { parseStructure } from "./StructureParser";
import { parseCP2KOutput, parseDeepMDLoss, parseLAMMPSThermo, parseVASPOSZICAR } from "./CP2KParser";

// ── Recognition result ───────────────────────────────────────────────

export type SciFileKind =
  | "structure"      // XYZ, PDB, CIF
  | "cp2k_input"     // CP2K input file (*.inp)
  | "cp2k_output"    // CP2K energy/SCF output
  | "lammps_input"   // LAMMPS input script
  | "lammps_thermo"  // LAMMPS thermo data
  | "deepmd_curve"   // DeepMD lcurve.out
  | "deepmd_input"   // DeepMD input.json
  | "vasp_oszicar"   // VASP OSZICAR
  | "vasp_poscar"    // VASP POSCAR
  | "trajectory"     // XYZ trajectory, dump, etc.
  | "density"        // .cub, .cube charge density
  | "slurm_output"   // Slurm .out/.err
  | "slurm_script"   // Slurm batch script
  | "generic_text"   // plain text, no special handling
  | "binary";        // unrecognized binary

export interface SciFileSummary {
  kind: SciFileKind;
  label: string;
  description: string;
  metrics: { label: string; value: string }[];
  suggestedViewer: "structure" | "results" | "hpc" | "text" | "external";
  externalTool?: string;  // e.g. "VMD", "VESTA"
}

// ── Extension mapping ────────────────────────────────────────────────

const EXT_MAP: Record<string, SciFileKind> = {
  xyz: "structure", pdb: "structure", ent: "structure",
  cif: "structure", mol2: "structure", gro: "structure",
  poscar: "vasp_poscar", POSCAR: "vasp_poscar",
  inp: "cp2k_input",   // CP2K input
  cub: "density", cube: "density", chg: "density",
  dcd: "trajectory", xtc: "trajectory", trr: "trajectory",
  lammpstrj: "trajectory", dump: "trajectory",
};

// ── Content-based recognition ────────────────────────────────────────

const CONTENT_SIGNATURES: Array<{
  pattern: RegExp;
  kind: SciFileKind;
  label: string;
}> = [
  // CP2K
  { pattern: /&(?:GLOBAL|FORCE_EVAL|DFT|MOTION|SUBSYS)/, kind: "cp2k_input", label: "CP2K 输入" },
  { pattern: /ENERGY\|\s*Total FORCE_EVAL/, kind: "cp2k_output", label: "CP2K 能量输出" },
  { pattern: /\bCP2K\b.*\b(?:version|input)\b/i, kind: "cp2k_output", label: "CP2K 输出" },
  // LAMMPS
  { pattern: /LAMMPS\s+\(\d+/, kind: "lammps_thermo", label: "LAMMPS 输出" },
  { pattern: /^\s*Step\s+Temp\s+Press/m, kind: "lammps_thermo", label: "LAMMPS Thermo" },
  { pattern: /^\s*(?:units|atom_style|boundary|pair_style|kspace_style)\s/, kind: "lammps_input", label: "LAMMPS 输入" },
  // DeepMD
  { pattern: /^#\s+step\s+(?:loss|l2_energy)/m, kind: "deepmd_curve", label: "DeepMD 训练曲线" },
  { pattern: /"model"\s*:\s*\{/, kind: "deepmd_input", label: "DeepMD 输入" },
  // VASP
  { pattern: /^\s*\d+\s+F=\s+[-\d.Ee+]+/m, kind: "vasp_oszicar", label: "VASP OSZICAR" },
  { pattern: /vasp\.\d+\.\d+/, kind: "vasp_oszicar", label: "VASP 输出" },
  // Slurm
  { pattern: /Submitted batch job/, kind: "slurm_output", label: "Slurm 输出" },
  { pattern: /^#SBATCH\s/, kind: "slurm_script", label: "Slurm 脚本" },
  { pattern: /^#PBS\s/, kind: "slurm_script", label: "PBS 脚本" },
  // Fallback
  { pattern: /^\s*\d+/m, kind: "generic_text", label: "文本文件" },
];

// ── Main API ─────────────────────────────────────────────────────────

export function recognizeSciFile(
  filename: string,
  content: string,
  sizeBytes: number,
): SciFileSummary {
  // 1. Extension-based
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const extKind = EXT_MAP[ext];
  if (extKind) {
    return buildSummary(extKind, filename, content, sizeBytes);
  }

  // 2. Content-based
  for (const sig of CONTENT_SIGNATURES) {
    if (sig.pattern.test(content.slice(0, 2000))) {
      return buildSummary(sig.kind, filename, content, sizeBytes);
    }
  }

  // 3. Binary check
  if (content.includes("\x00") || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(content.slice(0, 100))) {
    return {
      kind: "binary",
      label: "二进制文件",
      description: `${sizeBytes} bytes`,
      metrics: [{ label: "大小", value: formatBytes(sizeBytes) }],
      suggestedViewer: "external",
    };
  }

  return {
    kind: "generic_text",
    label: "文本文件",
    description: filename,
    metrics: [{ label: "大小", value: formatBytes(sizeBytes) }],
    suggestedViewer: "text",
  };
}

/** Extract summary metrics from recognized files. */
export function extractSciMetrics(
  kind: SciFileKind,
  content: string,
): { label: string; value: string }[] {
  switch (kind) {
    case "structure": {
      try {
        const s = parseStructure(content);
        const m: { label: string; value: string }[] = [
          { label: "原子数", value: String(s.atoms.length) },
          { label: "格式", value: s.format.toUpperCase() },
        ];
        if (s.unitCell) {
          m.push({
            label: "晶胞",
            value: `${s.unitCell.a.toFixed(1)}×${s.unitCell.b.toFixed(1)}×${s.unitCell.c.toFixed(1)} Å`,
          });
        }
        // Element counts
        const elemCounts: Record<string, number> = {};
        for (const a of s.atoms) {
          elemCounts[a.element] = (elemCounts[a.element] ?? 0) + 1;
        }
        const formula = Object.entries(elemCounts)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([el, n]) => (n > 1 ? `${el}${n}` : el))
          .join("");
        if (formula) m.push({ label: "化学式", value: formula });
        return m;
      } catch {
        return [{ label: "格式", value: kind }];
      }
    }

    case "cp2k_output": {
      const { energies } = parseCP2KOutput(content);
      const m: { label: string; value: string }[] = [
        { label: "能量步数", value: String(energies.length) },
      ];
      if (energies.length > 0) {
        const last = energies[energies.length - 1];
        m.push({ label: "最终能量", value: `${last.energy.toFixed(6)} Eh` });
        m.push({ label: "收敛", value: last.converged ? "✓" : "✗" });
      }
      return m;
    }

    case "lammps_thermo": {
      const steps = parseLAMMPSThermo(content);
      const m: { label: string; value: string }[] = [
        { label: "MD 步数", value: String(steps.length) },
      ];
      if (steps.length > 0) {
        const avgT = steps.reduce((a, b) => a + b.temperature, 0) / steps.length;
        m.push({ label: "平均温度", value: `${avgT.toFixed(1)} K` });
      }
      return m;
    }

    case "deepmd_curve": {
      const pts = parseDeepMDLoss(content);
      const m: { label: string; value: string }[] = [
        { label: "训练步数", value: String(pts.length) },
      ];
      if (pts.length > 0) {
        m.push({ label: "最终 Loss", value: pts[pts.length - 1].loss.toExponential(3) });
      }
      return m;
    }

    case "vasp_oszicar": {
      const pts = parseVASPOSZICAR(content);
      return [
        { label: "离子步数", value: String(pts.length) },
        ...(pts.length > 0
          ? [{ label: "最终能量", value: `${pts[pts.length - 1].energy.toFixed(6)} eV` }]
          : []),
      ];
    }

    default:
      return [{ label: "大小", value: formatBytes(content.length) }];
  }
}

// ── External tool launcher ───────────────────────────────────────────

export interface ExternalTool {
  name: string;
  label: string;
  fileKinds: SciFileKind[];
  command: string;  // template — {path} is replaced
}

export const EXTERNAL_TOOLS: ExternalTool[] = [
  {
    name: "vmd",
    label: "VMD",
    fileKinds: ["structure", "trajectory", "density"],
    command: "vmd {path}",
  },
  {
    name: "vesta",
    label: "VESTA",
    fileKinds: ["structure", "density"],
    command: "VESTA {path}",
  },
  {
    name: "python",
    label: "Python",
    fileKinds: ["cp2k_output", "lammps_thermo", "deepmd_curve", "vasp_oszicar"],
    command: "python -c \"import sys; print(open('{path}').read())\"",
  },
  {
    name: "less",
    label: "终端查看",
    fileKinds: ["cp2k_output", "lammps_thermo", "slurm_output", "generic_text"],
    command: "less {path}",
  },
];

export function getToolsForKind(kind: SciFileKind): ExternalTool[] {
  return EXTERNAL_TOOLS.filter((t) => t.fileKinds.includes(kind));
}

// ── Helpers ──────────────────────────────────────────────────────────

function buildSummary(
  kind: SciFileKind,
  filename: string,
  content: string,
  sizeBytes: number,
): SciFileSummary {
  const metrics = extractSciMetrics(kind, content);
  metrics.unshift({ label: "大小", value: formatBytes(sizeBytes) });

  const suggestedViewer =
    kind === "structure" || kind === "trajectory" || kind === "density" ? "structure"
    : kind === "cp2k_output" || kind === "lammps_thermo" || kind === "deepmd_curve" || kind === "vasp_oszicar" ? "results"
    : kind === "slurm_output" ? "hpc"
    : "text";

  const externalTool =
    kind === "structure" ? "VMD / VESTA"
    : kind === "trajectory" ? "VMD"
    : kind === "density" ? "VESTA"
    : undefined;

  return {
    kind,
    label: LABELS[kind] ?? kind,
    description: filename,
    metrics,
    suggestedViewer,
    externalTool,
  };
}

const LABELS: Record<SciFileKind, string> = {
  structure: "分子结构",
  cp2k_input: "CP2K 输入",
  cp2k_output: "CP2K 输出",
  lammps_input: "LAMMPS 输入",
  lammps_thermo: "LAMMPS 热力学",
  deepmd_input: "DeepMD 输入",
  deepmd_curve: "DeepMD 训练",
  vasp_oszicar: "VASP OSZICAR",
  vasp_poscar: "VASP POSCAR",
  trajectory: "轨迹文件",
  density: "电荷密度",
  slurm_output: "Slurm 输出",
  slurm_script: "Slurm 脚本",
  generic_text: "文本文件",
  binary: "二进制文件",
};

// ── Artifact lineage ─────────────────────────────────────────────────

export interface ArtifactNode {
  id: string;
  name: string;
  path: string;
  kind: SciFileKind;
  runId?: string;
  toolCallId?: string;
  jobId?: string;
  parentIds: string[];
  createdAt: number;
  sizeBytes: number;
}

export class ArtifactLineage {
  private nodes = new Map<string, ArtifactNode>();

  add(node: ArtifactNode): void {
    this.nodes.set(node.id, node);
  }

  get(id: string): ArtifactNode | undefined {
    return this.nodes.get(id);
  }

  /** Return the ancestry chain from *id* back to the root. */
  ancestry(id: string): ArtifactNode[] {
    const chain: ArtifactNode[] = [];
    const visited = new Set<string>();
    let current = this.nodes.get(id);
    while (current && !visited.has(current.id)) {
      visited.add(current.id);
      chain.push(current);
      const parentId = current.parentIds[0];
      current = parentId ? this.nodes.get(parentId) : undefined;
    }
    return chain;
  }

  /** Return all nodes that descend from *parentId*. */
  descendants(parentId: string): ArtifactNode[] {
    const result: ArtifactNode[] = [];
    for (const node of this.nodes.values()) {
      if (node.parentIds.includes(parentId)) {
        result.push(node);
        result.push(...this.descendants(node.id));
      }
    }
    return result;
  }

  /** Return a flat list sorted by creation time. */
  list(): ArtifactNode[] {
    return [...this.nodes.values()].sort((a, b) => a.createdAt - b.createdAt);
  }

  clear(): void {
    this.nodes.clear();
  }
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}
