/** HPC Run Viewer — Slurm job monitoring, logs, queue status.
 *
 * Displays job cards with state, partition, elapsed time, node info.
 * Supports: view output, cancel job, copy job ID, queue listing.
 */

import React, { useState } from "react";

// ── Types ────────────────────────────────────────────────────────────

export type SlurmJobState = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED" | "TIMEOUT";

export interface SlurmJob {
  jobId: string;
  name: string;
  state: SlurmJobState;
  partition?: string;
  nodeList?: string;
  elapsed?: string;       // e.g. "00:21:08"
  timeLimit?: string;
  submitTime?: string;
  workDir?: string;
  outputFile?: string;
  errorFile?: string;
  exitCode?: number;
}

export interface SlurmQueue {
  jobs: SlurmJob[];
  total: number;
  running: number;
  pending: number;
}

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  queue?: SlurmQueue;
  activeJob?: SlurmJob;
  logContent?: string;
  onCancelJob?: (jobId: string) => void;
  onViewLog?: (jobId: string) => void;
  onRefreshQueue?: () => void;
}

// ── Component ────────────────────────────────────────────────────────

export const HPCRunViewer: React.FC<Props> = ({
  queue,
  activeJob,
  logContent,
  onCancelJob,
  onViewLog,
  onRefreshQueue,
}) => {
  const [expandedJob, setExpandedJob] = useState<string | null>(null);

  const toggleJob = (id: string) => {
    setExpandedJob((prev) => (prev === id ? null : id));
  };

  if (!queue?.jobs.length && !activeJob) {
    return <div className="inspector-placeholder">暂无 HPC 作业</div>;
  }

  return (
    <div className="hpc-viewer">
      {/* Queue summary */}
      {queue && (
        <div className="sci-metrics" style={{ marginBottom: 12 }}>
          <div className="sci-metric">
            <div className="sci-metric-label">总作业</div>
            <div className="sci-metric-value">{queue.total}</div>
          </div>
          <div className="sci-metric">
            <div className="sci-metric-label">运行中</div>
            <div className="sci-metric-value" style={{ color: "#3b82f6" }}>{queue.running}</div>
          </div>
          <div className="sci-metric">
            <div className="sci-metric-label">等待中</div>
            <div className="sci-metric-value" style={{ color: "#f59e0b" }}>{queue.pending}</div>
          </div>
        </div>
      )}

      {/* Active job detail */}
      {activeJob && (
        <JobCard
          job={activeJob}
          expanded={true}
          logContent={activeJob.jobId === expandedJob ? logContent : undefined}
          onToggle={() => toggleJob(activeJob.jobId)}
          onCancel={onCancelJob}
          onViewLog={onViewLog}
        />
      )}

      {/* Queue list */}
      {queue?.jobs.map((job) => (
        <JobCard
          key={job.jobId}
          job={job}
          expanded={job.jobId === expandedJob}
          logContent={job.jobId === expandedJob ? logContent : undefined}
          onToggle={() => toggleJob(job.jobId)}
          onCancel={onCancelJob}
          onViewLog={onViewLog}
        />
      ))}

      {/* Refresh */}
      {onRefreshQueue && (
        <button className="hpc-btn" style={{ marginTop: 8 }} onClick={onRefreshQueue}>
          刷新队列
        </button>
      )}
    </div>
  );
};

// ── Job card ─────────────────────────────────────────────────────────

const JobCard: React.FC<{
  job: SlurmJob;
  expanded: boolean;
  logContent?: string;
  onToggle: () => void;
  onCancel?: (jobId: string) => void;
  onViewLog?: (jobId: string) => void;
}> = ({ job, expanded, logContent, onToggle, onCancel, onViewLog }) => {
  const handleCopyId = () => {
    navigator.clipboard.writeText(job.jobId).catch(() => {});
  };

  return (
    <div className="hpc-job-card">
      <div className="hpc-job-header" onClick={onToggle} style={{ cursor: "pointer" }}>
        <span className="hpc-job-id">{job.jobId}</span>
        <span className={`hpc-job-state ${job.state}`}>
          {job.state}
        </span>
      </div>

      <div className="hpc-job-meta">
        {job.name && <><span className="hpc-job-label">名称</span><span className="hpc-job-value">{job.name}</span></>}
        {job.partition && <><span className="hpc-job-label">分区</span><span className="hpc-job-value">{job.partition}</span></>}
        {job.elapsed && <><span className="hpc-job-label">耗时</span><span className="hpc-job-value">{job.elapsed}</span></>}
        {job.nodeList && <><span className="hpc-job-label">节点</span><span className="hpc-job-value">{job.nodeList}</span></>}
        {job.workDir && <><span className="hpc-job-label">目录</span><span className="hpc-job-value" style={{ fontSize: 11 }}>{job.workDir}</span></>}
      </div>

      <div className="hpc-job-actions">
        {onViewLog && (
          <button className="hpc-btn" onClick={() => onViewLog(job.jobId)}>
            查看输出
          </button>
        )}
        <button className="hpc-btn" onClick={handleCopyId}>
          复制 Job ID
        </button>
        {onCancel && (job.state === "RUNNING" || job.state === "PENDING") && (
          <button className="hpc-btn hpc-btn-danger" onClick={() => onCancel(job.jobId)}>
            取消作业
          </button>
        )}
      </div>

      {expanded && logContent && (
        <div className="hpc-log">{logContent.slice(0, 10000)}</div>
      )}
    </div>
  );
};
