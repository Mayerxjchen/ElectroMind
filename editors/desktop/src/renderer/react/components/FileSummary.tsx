/** File summary card — structure info, calculation input, results preview.
 *
 * Replaces the 3D StructureViewer.  Shows parsed metadata with
 * "Open in VMD / OVITO / Avogadro / system default" actions.
 * For SSH/sandbox files, downloads to a managed temp dir first.
 */

import React from "react";
import type { SciFileSummary } from "../../parsers/SciFileRecognizer";
import { getToolsForKind } from "../../parsers/SciFileRecognizer";

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  summary: SciFileSummary;
  filename: string;
  onOpenWith?: (tool: string) => void;
  onOpenDefault?: () => void;
  onCopyPath?: () => void;
  downloading?: boolean;
}

// ── Component ────────────────────────────────────────────────────────

export const FileSummary: React.FC<Props> = ({
  summary,
  filename,
  onOpenWith,
  onOpenDefault,
  onCopyPath,
  downloading,
}) => {
  const tools = getToolsForKind(summary.kind);

  return (
    <div className="file-summary">
      {/* Header */}
      <div className="file-summary-header">
        <span className={`file-summary-kind file-kind-${summary.kind}`}>
          {summary.label}
        </span>
        <span className="file-summary-name">{filename}</span>
      </div>

      {/* Description */}
      {summary.description && (
        <p className="file-summary-desc">{summary.description}</p>
      )}

      {/* Metrics grid */}
      <div className="file-summary-metrics">
        {summary.metrics.map((m, i) => (
          <div key={i} className="file-summary-metric">
            <span className="file-summary-metric-label">{m.label}</span>
            <span className="file-summary-metric-value">{m.value}</span>
          </div>
        ))}
      </div>

      {/* External tool buttons */}
      <div className="file-summary-actions">
        {onOpenDefault && (
          <button className="file-summary-btn primary" onClick={onOpenDefault}>
            用默认程序打开
          </button>
        )}
        {tools.map((tool) => (
          <button
            key={tool.name}
            className="file-summary-btn"
            onClick={() => onOpenWith?.(tool.name)}
            title={tool.command}
          >
            在 {tool.label} 中打开
          </button>
        ))}
        {onCopyPath && (
          <button className="file-summary-btn" onClick={onCopyPath}>
            复制路径
          </button>
        )}
      </div>

      {/* Download indicator for remote files */}
      {downloading && (
        <div className="file-summary-downloading">
          正在从远程下载…
        </div>
      )}

      {/* External tool note */}
      {summary.externalTool && (
        <div className="file-summary-note">
          推荐使用 {summary.externalTool} 查看完整结构与轨迹。
        </div>
      )}
    </div>
  );
};

// ── CP2K Input summary parser ────────────────────────────────────────

export interface CP2KInputSummary {
  program: string;
  taskType: string;
  method: string;
  functional?: string;
  basisSet?: string;
  cutoffRy?: number;
  relCutoffRy?: number;
  temperature?: number;
  steps?: number;
  timestepFs?: number;
  ensemble?: string;
  cellABC?: [number, number, number];
  kpoints?: [number, number, number];
}

export function parseCP2KInput(text: string): CP2KInputSummary {
  const summary: CP2KInputSummary = {
    program: "CP2K",
    taskType: "ENERGY",
    method: "DFT",
  };

  // RUN_TYPE
  const runType = text.match(/RUN_TYPE\s+(\S+)/i);
  if (runType) summary.taskType = runType[1].toUpperCase();

  // METHOD (Quickstep) — detect DFTB, GPW, etc.
  if (text.includes("&DFTB") || text.includes("METHOD DFTB")) summary.method = "DFTB";
  else if (text.includes("&XTB")) summary.method = "xTB";
  else if (text.includes("&GAPW")) summary.method = "GAPW";

  // Functional
  const funcMatch = text.match(
    /XC_FUNCTIONAL\s+(?:\S+\s+)?(\S+)/i
  );
  if (funcMatch) summary.functional = funcMatch[1];

  // Basis set
  const basisMatch = text.match(/BASIS_SET_FILE_NAME\s+(\S+)/i);
  if (basisMatch) summary.basisSet = basisMatch[1];
  const dbasis = text.match(/DZVP|TZVP|TZV2P|QZVP|6-31G/i);
  if (dbasis) summary.basisSet = dbasis[0];

  // Cutoff
  const cutoff = text.match(/CUTOFF\s+(\d+)/i);
  if (cutoff) summary.cutoffRy = parseInt(cutoff[1], 10);
  const relCutoff = text.match(/REL_CUTOFF\s+(\d+)/i);
  if (relCutoff) summary.relCutoffRy = parseInt(relCutoff[1], 10);

  // Temperature
  const temp = text.match(/TEMPERATURE\s+(\d+\.?\d*)/i);
  if (temp) summary.temperature = parseFloat(temp[1]);

  // MD steps
  const steps = text.match(/STEPS\s+(\d+)/i);
  if (steps) summary.steps = parseInt(steps[1], 10);

  // Timestep
  const ts = text.match(/TIMESTEP\s+(\d+\.?\d*)/i);
  if (ts) summary.timestepFs = parseFloat(ts[1]);

  // Ensemble
  const ensemble = text.match(/ENSEMBLE\s+(\S+)/i);
  if (ensemble) summary.ensemble = ensemble[1];

  // Cell
  const cellA = text.match(/\bA\s+(\d+\.?\d*)\s+(\d+\.?\d*)\s+(\d+\.?\d*)/i);
  if (cellA) {
    summary.cellABC = [
      parseFloat(cellA[1]),
      parseFloat(cellA[2]),
      parseFloat(cellA[3]),
    ];
  }

  // K-points
  const kp = text.match(/KPOINTS\s+(\d+)\s+(\d+)\s+(\d+)/i);
  if (kp) {
    summary.kpoints = [
      parseInt(kp[1], 10),
      parseInt(kp[2], 10),
      parseInt(kp[3], 10),
    ];
  }

  return summary;
}
