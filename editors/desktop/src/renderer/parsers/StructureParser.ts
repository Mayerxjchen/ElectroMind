/** Molecular structure parser — XYZ, PDB, CIF → unified AtomData.
 *
 * Each parser returns ``ParsedStructure`` with atoms, unit cell info,
 * and format-specific metadata for the StructureViewer.
 */

// ── Common types ─────────────────────────────────────────────────────

export interface AtomData {
  element: string;     // e.g. "C", "O", "Fe"
  x: number;
  y: number;
  z: number;
  residue?: string;    // from PDB
  chain?: string;      // from PDB
  atomName?: string;   // from PDB/CIF
  serial?: number;     // from PDB
  charge?: number;
}

export interface UnitCell {
  a: number; b: number; c: number;
  alpha: number; beta: number; gamma: number;
}

export interface ParsedStructure {
  atoms: AtomData[];
  title?: string;
  unitCell?: UnitCell;
  format: "xyz" | "pdb" | "cif";
  metadata: Record<string, string>;
}

// ── Element properties ───────────────────────────────────────────────

const COVALENT_RADII: Record<string, number> = {
  H: 0.31, He: 0.28, Li: 1.28, Be: 0.96, B: 0.84, C: 0.76, N: 0.71,
  O: 0.66, F: 0.57, Ne: 0.58, Na: 1.66, Mg: 1.41, Al: 1.21, Si: 1.11,
  P: 1.07, S: 1.05, Cl: 1.02, Ar: 1.06, K: 2.03, Ca: 1.76, Sc: 1.70,
  Ti: 1.60, V: 1.53, Cr: 1.39, Mn: 1.39, Fe: 1.32, Co: 1.26, Ni: 1.24,
  Cu: 1.32, Zn: 1.22, Ga: 1.22, Ge: 1.20, As: 1.19, Se: 1.20, Br: 1.20,
  Kr: 1.16, Rb: 2.20, Sr: 1.95, Y: 1.90, Zr: 1.75, Nb: 1.64, Mo: 1.54,
  Tc: 1.47, Ru: 1.46, Rh: 1.42, Pd: 1.39, Ag: 1.45, Cd: 1.44, In: 1.42,
  Sn: 1.39, Sb: 1.39, Te: 1.38, I: 1.39, Xe: 1.40,
};

const ELEMENT_COLORS: Record<string, number> = {
  H:  0xffffff, He: 0xd9ffff, Li: 0xcc80ff, Be: 0xc2ff00, B:  0xffb5b5,
  C:  0x909090, N:  0x3050f8, O:  0xff0d0d, F:  0x90e050, Ne: 0xb3e3f5,
  Na: 0xab5cf2, Mg: 0x8aff00, Al: 0xbfa6a6, Si: 0xf0c8a0, P:  0xff8000,
  S:  0xffff30, Cl: 0x1ff01f, Ar: 0x80d1e3, K:  0x8f40d4, Ca: 0x3dff00,
  Sc: 0xe6e6e6, Ti: 0xbfc2c7, V:  0xa6a6ab, Cr: 0x8a99c7, Mn: 0x9c7ac7,
  Fe: 0xe06633, Co: 0xf090a0, Ni: 0x50d050, Cu: 0xc88033, Zn: 0x7d80b0,
};

export function elementColor(el: string): number {
  return ELEMENT_COLORS[el] ?? 0xff1493;
}

export function covalentRadius(el: string): number {
  return COVALENT_RADII[el] ?? 0.7;
}

// ── XYZ parser ───────────────────────────────────────────────────────

export function parseXYZ(text: string): ParsedStructure {
  const lines = text.trim().split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.length < 2) throw new Error("Invalid XYZ: too few lines");

  const natoms = parseInt(lines[0], 10);
  if (isNaN(natoms)) throw new Error("Invalid XYZ: first line must be atom count");

  const title = lines[1] || "";
  const atoms: AtomData[] = [];

  for (let i = 2; i < Math.min(2 + natoms, lines.length); i++) {
    const parts = lines[i].split(/\s+/);
    if (parts.length < 4) continue;
    atoms.push({
      element: parts[0],
      x: parseFloat(parts[1]),
      y: parseFloat(parts[2]),
      z: parseFloat(parts[3]),
    });
  }

  return { atoms, title, format: "xyz", metadata: {} };
}

// ── PDB parser (ATOM/HETATM records only) ────────────────────────────

export function parsePDB(text: string): ParsedStructure {
  const atoms: AtomData[] = [];
  let title = "";
  const cell: Partial<UnitCell> = {};

  for (const line of text.split("\n")) {
    const record = line.slice(0, 6).trim();

    if (record === "TITLE" && !title) {
      title = line.slice(10).trim();
    }
    if (record === "CRYST1") {
      cell.a = parseFloat(line.slice(6, 15));
      cell.b = parseFloat(line.slice(15, 24));
      cell.c = parseFloat(line.slice(24, 33));
      cell.alpha = parseFloat(line.slice(33, 40));
      cell.beta = parseFloat(line.slice(40, 47));
      cell.gamma = parseFloat(line.slice(47, 54));
    }
    if (record === "ATOM" || record === "HETATM") {
      atoms.push({
        serial: parseInt(line.slice(6, 11), 10),
        atomName: line.slice(12, 16).trim(),
        residue: line.slice(17, 20).trim(),
        chain: line.slice(21, 22).trim(),
        element: line.slice(76, 78).trim() || line.slice(12, 14).trim(),
        x: parseFloat(line.slice(30, 38)),
        y: parseFloat(line.slice(38, 46)),
        z: parseFloat(line.slice(46, 54)),
      });
    }
  }

  const unitCell =
    cell.a && cell.b && cell.c
      ? {
          a: cell.a!, b: cell.b!, c: cell.c!,
          alpha: cell.alpha ?? 90, beta: cell.beta ?? 90, gamma: cell.gamma ?? 90,
        }
      : undefined;

  return { atoms, title, unitCell, format: "pdb", metadata: {} };
}

// ── CIF parser (minimal — atom_site loop only) ───────────────────────

export function parseCIF(text: string): ParsedStructure {
  const atoms: AtomData[] = [];
  let title = "";
  const cell: Partial<UnitCell> = {};

  // Find atom_site loop
  const atomSection = text.match(/_atom_site_fract_x\b[\s\S]*?(?=\n\s*\n|$)/);
  const cellA = text.match(/_cell_length_a\s+([\d.]+)/);
  const cellB = text.match(/_cell_length_b\s+([\d.]+)/);
  const cellC = text.match(/_cell_length_c\s+([\d.]+)/);
  const cellAlpha = text.match(/_cell_angle_alpha\s+([\d.]+)/);
  const cellBeta = text.match(/_cell_angle_beta\s+([\d.]+)/);
  const cellGamma = text.match(/_cell_angle_gamma\s+([\d.]+)/);
  const titleMatch = text.match(/_chemical_name_common\s+'([^']+)'/);

  if (titleMatch) title = titleMatch[1];
  if (cellA) cell.a = parseFloat(cellA[1]);
  if (cellB) cell.b = parseFloat(cellB[1]);
  if (cellC) cell.c = parseFloat(cellC[1]);
  if (cellAlpha) cell.alpha = parseFloat(cellAlpha[1]);
  if (cellBeta) cell.beta = parseFloat(cellBeta[1]);
  if (cellGamma) cell.gamma = parseFloat(cellGamma[1]);

  // Parse atom_site data rows (lines starting with atom label after the loop_ header)
  if (atomSection) {
    const lines = atomSection[0].split("\n");
    let inData = false;
    for (const line of lines) {
      if (line.startsWith("_")) continue;
      if (line.startsWith("loop_")) { inData = true; continue; }
      if (!inData) continue;
      const parts = line.trim().split(/\s+/);
      if (parts.length < 4) continue;
      // Typical CIF order: label, symbol, fract_x, fract_y, fract_z
      const label = parts[0];
      const symbol = parts.length >= 5 ? parts[1] : label.replace(/[0-9]/g, "");
      const fx = parseFloat(parts[parts.length - 3]);
      const fy = parseFloat(parts[parts.length - 2]);
      const fz = parseFloat(parts[parts.length - 1]);
      if (isNaN(fx)) continue;
      atoms.push({
        element: symbol,
        x: fx, y: fy, z: fz,  // fractional coordinates
        atomName: label,
      });
    }
  }

  const unitCell =
    cell.a && cell.b && cell.c
      ? { a: cell.a!, b: cell.b!, c: cell.c!, alpha: cell.alpha ?? 90, beta: cell.beta ?? 90, gamma: cell.gamma ?? 90 }
      : undefined;

  return { atoms, title, unitCell, format: "cif", metadata: {} };
}

// ── Auto-detect format ───────────────────────────────────────────────

export function parseStructure(text: string, filename?: string): ParsedStructure {
  // Detect by filename extension
  const ext = filename?.split(".").pop()?.toLowerCase();
  if (ext === "xyz") return parseXYZ(text);
  if (ext === "pdb" || ext === "ent") return parsePDB(text);
  if (ext === "cif") return parseCIF(text);

  // Detect by content
  const firstLine = text.trim().split("\n")[0]?.trim() ?? "";
  if (/^\d+\s*$/.test(firstLine)) return parseXYZ(text);
  if (firstLine.startsWith("HEADER") || firstLine.startsWith("ATOM") || firstLine.startsWith("TITLE")) return parsePDB(text);
  if (text.includes("_cell_length_a") || text.includes("_atom_site_fract_x")) return parseCIF(text);

  throw new Error("无法识别的结构文件格式。支持 XYZ, PDB, CIF。");
}
