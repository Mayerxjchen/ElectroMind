/** Scientific Results viewer — CP2K, LAMMPS, DeepMD, VASP output analysis.
 *
 * Renders:
 * - Energy / force tables with convergence indicators
 * - SCF convergence sparklines
 * - MD trajectory summaries (T, P, Etot)
 * - DeepMD training loss curves
 * - Model deviation charts
 */

import React from "react";

// ── Types ────────────────────────────────────────────────────────────

export interface EnergyPoint {
  step: number;
  energy: number;       // Hartree
  deltaE?: number;      // convergence
  scfSteps?: number;
  converged: boolean;
}

export interface ForceStats {
  atom: string;
  fx: number;
  fy: number;
  fz: number;
  magnitude: number;
}

export interface MDStep {
  step: number;
  timeFs: number;
  temperature: number;  // K
  pressure: number;     // bar
  etot: number;
  ekin: number;
  epot: number;
  volume: number;
}

export interface DeepMDLoss {
  step: number;
  loss: number;
  l2Energy?: number;
  l2Force?: number;
}

export interface SCFCycle {
  iteration: number;
  energy: number;
  deltaE: number;
}

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  energies?: EnergyPoint[];
  forces?: ForceStats[];
  mdTrajectory?: MDStep[];
  deepmdLoss?: DeepMDLoss[];
  scfCycles?: SCFCycle[];
  cp2kOutput?: string;  // raw CP2K output for extraction
  title?: string;
}

// ── Component ────────────────────────────────────────────────────────

export const ScientificResults: React.FC<Props> = ({
  energies,
  forces,
  mdTrajectory,
  deepmdLoss,
  scfCycles,
  title,
}) => {
  if (!energies?.length && !forces?.length && !mdTrajectory?.length && !deepmdLoss?.length && !scfCycles?.length) {
    return <div className="inspector-placeholder">暂无科学计算结果</div>;
  }

  return (
    <div className="sci-results">
      {title && <h4 className="sci-section-title" style={{ marginBottom: 10 }}>{title}</h4>}
      {/* P2.1: TS 快速预览的结果未经确定性 Parser 校验，一律标注。 */}
      <div className="file-summary-unverified" title="TS 快速预览，未经确定性 Parser 校验">
        未验证
      </div>

      {/* Energy table */}
      {energies && energies.length > 0 && (
        <div className="sci-section">
          <div className="sci-section-header">
            <span className="sci-section-title">能量</span>
            <span className="sci-section-subtitle">{energies.length} steps</span>
          </div>
          <table className="sci-table">
            <thead>
              <tr>
                <th>Step</th>
                <th>Energy (Hartree)</th>
                <th>ΔE</th>
                <th>SCF</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {energies.slice(-20).map((e, i) => (
                <tr key={i}>
                  <td>{e.step}</td>
                  <td>{e.energy.toFixed(8)}</td>
                  <td>{e.deltaE != null ? e.deltaE.toExponential(2) : "—"}</td>
                  <td>{e.scfSteps ?? "—"}</td>
                  <td className={e.converged ? "converged" : "not-converged"}>
                    {e.converged ? "✓" : "✗"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* Energy sparkline */}
          {energies.length > 1 && (
            <BarChart
              data={energies.slice(-60).map((e) => e.energy)}
              height={40}
              color="var(--primary)"
            />
          )}
        </div>
      )}

      {/* Forces */}
      {forces && forces.length > 0 && (
        <div className="sci-section">
          <div className="sci-section-header">
            <span className="sci-section-title">力</span>
          </div>
          <table className="sci-table">
            <thead>
              <tr>
                <th>Atom</th>
                <th>Fx</th>
                <th>Fy</th>
                <th>Fz</th>
                <th>|F|</th>
              </tr>
            </thead>
            <tbody>
              {forces.map((f, i) => (
                <tr key={i}>
                  <td>{f.atom}</td>
                  <td>{f.fx.toFixed(6)}</td>
                  <td>{f.fy.toFixed(6)}</td>
                  <td>{f.fz.toFixed(6)}</td>
                  <td>{f.magnitude.toFixed(6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* SCF convergence */}
      {scfCycles && scfCycles.length > 0 && (
        <div className="sci-section">
          <div className="sci-section-header">
            <span className="sci-section-title">SCF 收敛</span>
            <span className="sci-section-subtitle">{scfCycles.length} cycles</span>
          </div>
          <BarChart
            data={scfCycles.map((c) => Math.log10(Math.max(c.deltaE, 1e-12)))}
            height={50}
            color="#22c55e"
            labels
          />
        </div>
      )}

      {/* MD trajectory summary */}
      {mdTrajectory && mdTrajectory.length > 0 && (
        <div className="sci-section">
          <div className="sci-section-header">
            <span className="sci-section-title">MD 轨迹</span>
            <span className="sci-section-subtitle">{mdTrajectory.length} frames</span>
          </div>
          <div className="sci-metrics">
            <MDStat label="温度" value={mean(mdTrajectory.map((s) => s.temperature))} unit="K" />
            <MDStat label="压力" value={mean(mdTrajectory.map((s) => s.pressure))} unit="bar" />
            <MDStat label="Etot" value={mean(mdTrajectory.map((s) => s.etot))} unit="a.u." />
            <MDStat label="体积" value={mean(mdTrajectory.map((s) => s.volume))} unit="Å³" />
          </div>
          <BarChart
            data={mdTrajectory.slice(-60).map((s) => s.temperature)}
            height={40}
            color="#f59e0b"
            labels
          />
          <div className="sci-chart-label">
            <span>Temperature (K)</span>
            <span>{mdTrajectory[mdTrajectory.length - 1]?.temperature.toFixed(1)} K</span>
          </div>
        </div>
      )}

      {/* DeepMD loss */}
      {deepmdLoss && deepmdLoss.length > 0 && (
        <div className="sci-section">
          <div className="sci-section-header">
            <span className="sci-section-title">DeepMD 训练</span>
            <span className="sci-section-subtitle">{deepmdLoss.length} steps</span>
          </div>
          <div className="sci-metrics">
            <MDStat
              label="Loss"
              value={deepmdLoss[deepmdLoss.length - 1]?.loss ?? 0}
              unit=""
              precision={6}
            />
            {deepmdLoss[0]?.l2Energy != null && (
              <MDStat
                label="L2 Energy"
                value={deepmdLoss[deepmdLoss.length - 1]?.l2Energy ?? 0}
                unit=""
                precision={6}
              />
            )}
            {deepmdLoss[0]?.l2Force != null && (
              <MDStat
                label="L2 Force"
                value={deepmdLoss[deepmdLoss.length - 1]?.l2Force ?? 0}
                unit=""
                precision={6}
              />
            )}
          </div>
          <BarChart
            data={deepmdLoss.map((d) => Math.log10(Math.max(d.loss, 1e-10)))}
            height={50}
            color="#8b5cf6"
            labels
          />
          <div className="sci-chart-label">
            <span>log₁₀(Loss)</span>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Helpers ──────────────────────────────────────────────────────────

function mean(arr: number[]): number {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

// ── Inline bar chart ─────────────────────────────────────────────────

const BarChart: React.FC<{
  data: number[];
  height: number;
  color: string;
  labels?: boolean;
}> = ({ data, height, color, labels }) => {
  if (!data.length) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  return (
    <div>
      <div className="sci-chart" style={{ height }}>
        {data.map((v, i) => (
          <div
            key={i}
            className="sci-chart-bar"
            style={{
              height: `${Math.max(2, ((v - min) / range) * height)}px`,
              background: color,
            }}
            title={labels ? `${v.toExponential(2)}` : v.toFixed(4)}
          />
        ))}
      </div>
    </div>
  );
};

// ── Metric tile ──────────────────────────────────────────────────────

const MDStat: React.FC<{
  label: string;
  value: number;
  unit: string;
  precision?: number;
}> = ({ label, value, unit, precision = 1 }) => (
  <div className="sci-metric">
    <div className="sci-metric-label">{label}</div>
    <div className="sci-metric-value">
      {value.toFixed(precision)}
      <span className="sci-metric-unit">{unit}</span>
    </div>
  </div>
);
