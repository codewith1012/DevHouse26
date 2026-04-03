import { useEffect, useMemo, useState } from "react";

const issueColumns = [
  { key: "issue_id", label: "Issue ID" },
  { key: "title", label: "Title" },
  { key: "status", label: "Status" },
  { key: "priority", label: "Priority" },
  { key: "project_key", label: "Project" },
  { key: "commits", label: "Linked Commit IDs" },
  { key: "commit_names", label: "Linked Commit Names" },
];

const commitColumns = [
  { key: "timestamp", label: "Time" },
  { key: "author", label: "Author" },
  { key: "message", label: "Commit Name" },
  { key: "repository_name", label: "Repository" },
  { key: "total_changes", label: "Changes" },
  { key: "attendance_pct", label: "Attendance %" },
];

const linkedCommitColumns = [
  { key: "issue_id", label: "Issue ID" },
  { key: "commit_id", label: "Commit ID" },
  { key: "message", label: "Commit Name" },
  { key: "author", label: "Author" },
  { key: "repository_name", label: "Repository" },
];

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const navItems = [
  { id: "overview", label: "Overview" },
  { id: "issues", label: "Issues" },
  { id: "commits", label: "Commits" },
  { id: "links", label: "Links" },
];

function App() {
  const [events, setEvents] = useState([]);
  const [issues, setIssues] = useState([]);
  const [syncInfo, setSyncInfo] = useState(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeSection, setActiveSection] = useState("overview");

  useEffect(() => {
    async function loadDashboard() {
      setLoading(true);
      setError("");

      try {
        const response = await fetch(`${API_BASE_URL}/api/dashboard`);
        if (!response.ok) {
          throw new Error(`Backend request failed with ${response.status}`);
        }

        const payload = await response.json();
        setEvents(payload.events ?? []);
        setIssues(payload.issues ?? []);
        setSyncInfo(payload.sync ?? null);
      } catch (fetchError) {
        setError(fetchError.message || "Failed to load dashboard");
      } finally {
        setLoading(false);
      }
    }

    loadDashboard();
  }, []);

  const filteredEvents = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return events;
    }

    return events.filter((event) =>
      [event.message, event.author, event.repository_name, event.commit_id, event.issue_id]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [events, query]);

  const filteredIssues = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return issues;
    }

    return issues.filter((issue) =>
      [issue.issue_id, issue.title, issue.status, issue.priority, issue.project_key, ...(issue.commits ?? [])]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [issues, query]);

  const linkedIssues = useMemo(
    () => issues.filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0).length,
    [issues],
  );

  const totalChanges = useMemo(
    () => events.reduce((sum, event) => sum + Number(event.total_changes || 0), 0),
    [events],
  );

  const avgAttendance = useMemo(() => {
    const values = events.map((event) => Number(event.attendance_pct)).filter((value) => !Number.isNaN(value));
    if (!values.length) {
      return 0;
    }

    return values.reduce((sum, value) => sum + value, 0) / values.length;
  }, [events]);

  const statusBreakdown = useMemo(() => groupCounts(issues, "status"), [issues]);
  const priorityBreakdown = useMemo(() => groupCounts(issues, "priority"), [issues]);
  const developerBreakdown = useMemo(() => groupCounts(events, "author"), [events]);
  const repositoryBreakdown = useMemo(() => groupCounts(events, "repository_name"), [events]);
  const totalLinkedCommits = useMemo(
    () => issues.reduce((sum, issue) => sum + (Array.isArray(issue.commits) ? issue.commits.length : 0), 0),
    [issues],
  );

  const linkedCommitDetails = useMemo(() => {
    const eventMap = new Map(events.map((event) => [event.commit_id, event]));

    return issues
      .filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0)
      .map((issue) => ({
        issue_id: issue.issue_id,
        title: issue.title,
        commits: issue.commits.map((commitId) => eventMap.get(commitId) || { commit_id: commitId, message: "Commit not found in current feed" }),
      }));
  }, [events, issues]);

  const linkedCommitRows = useMemo(
    () =>
      linkedCommitDetails.flatMap((issue) =>
        issue.commits.map((commit) => ({
          issue_id: issue.issue_id,
          commit_id: commit.commit_id,
          message: commit.message ?? "N/A",
          author: commit.author ?? "N/A",
          repository_name: commit.repository_name ?? "N/A",
        })),
      ),
    [linkedCommitDetails],
  );

  const issueRows = useMemo(() => {
    const eventMap = new Map(events.map((event) => [event.commit_id, event]));

    return filteredIssues.slice(0, 12).map((issue) => {
      const commitIds = Array.isArray(issue.commits) ? issue.commits : [];
      const commitNames = commitIds
        .map((commitId) => eventMap.get(commitId)?.message || "Commit not found")
        .join(", ");

      return {
        ...issue,
        commits: commitIds.length ? commitIds.join(", ") : "No linked commits",
        commit_names: commitNames || "No linked commit names",
      };
    });
  }, [events, filteredIssues]);

  const filteredLinkedCommitRows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return linkedCommitRows;
    }

    return linkedCommitRows.filter((row) =>
      [row.issue_id, row.commit_id, row.message, row.author, row.repository_name]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [linkedCommitRows, query]);

  const topRepositories = repositoryBreakdown.slice(0, 5);
  const topDevelopers = developerBreakdown.slice(0, 5);

  return (
    <div className="page-shell">
      <header className="topbar">
        <div className="brand-block">
          <p className="brand-kicker">Devhouse Analytics</p>
          <h1>Engineering Dashboard</h1>
        </div>

        <nav className="topnav">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={item.id === activeSection ? "nav-item active" : "nav-item"}
              onClick={() => {
                setActiveSection(item.id);
                document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="page-content">
        <section className="hero-panel" id="overview">
          <div className="hero-copy">
            <p className="section-kicker">Operational Summary</p>
            <h2>Professional visibility into issues, commits, and live sync activity</h2>
            <p>
              The dashboard refreshes through FastAPI, updates commit links in Supabase, and presents a clean
              page-based view for issues, commits, and linkage history.
            </p>
          </div>

          <div className="hero-actions">
            <label className="search-panel">
              <span>Search across issues and commits</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by issue ID, commit ID, message, author, repo..."
              />
            </label>

            <div className="sync-summary">
              <span>Live Sync Status</span>
              <strong>{syncInfo ? `${syncInfo.linked_commits} linked commits` : "Waiting for sync"}</strong>
            </div>
          </div>
        </section>

        {loading ? (
          <section className="panel">Syncing and loading dashboard data...</section>
        ) : error ? (
          <section className="panel error-panel">{error}</section>
        ) : (
          <>
            <section className="stats-grid">
              <StatCard label="Extension Events" value={events.length} detail="Recent activity records" />
              <StatCard label="Tracked Issues" value={issues.length} detail="Records in req_code_mapping" />
              <StatCard label="Linked Issues" value={linkedIssues} detail="Issues with stored commit links" />
              <StatCard label="Linked Commits" value={totalLinkedCommits} detail="Commit IDs saved in req_code_mapping" />
              <StatCard label="Total Changes" value={totalChanges} detail="Aggregate additions and deletions" />
              <StatCard label="Avg Attendance" value={`${avgAttendance.toFixed(1)}%`} detail="Across event records" />
            </section>

            {syncInfo ? (
              <section className="panel sync-banner">
                <strong>Auto Sync</strong>
                <span>
                  Matched {syncInfo.matched_issues} issues and wrote {syncInfo.linked_commits} linked commits during this refresh.
                </span>
              </section>
            ) : null}

            <section className="section-block" id="issues">
              <div className="section-heading">
                <div>
                  <p className="section-kicker">Issue Management</p>
                  <h2>Issue register and operational breakdown</h2>
                </div>
              </div>

              <div className="content-grid">
                <Panel title="Issue Register">
                  <DataTable columns={issueColumns} rows={issueRows} emptyMessage="No issues matched the current search." />
                </Panel>

                <Panel title="Issue Status">
                  <BarList items={statusBreakdown} />
                </Panel>

                <Panel title="Issue Priority">
                  <BarList items={priorityBreakdown} />
                </Panel>

                <Panel title="Matching Overview">
                  <div className="notes">
                    <p>The backend now combines lightweight NLP scoring with code-aware signals from diff patches.</p>
                    <p>That means future commits can be linked automatically when their code and text actually resemble an issue.</p>
                    <p>The issue register shows both the stored commit IDs and the resolved commit names from the database.</p>
                  </div>
                </Panel>
              </div>
            </section>

            <section className="section-block" id="commits">
              <div className="section-heading">
                <div>
                  <p className="section-kicker">Commit Activity</p>
                  <h2>Recent engineering events and contributor trends</h2>
                </div>
              </div>

              <div className="content-grid">
                <Panel title="Recent Commits" className="span-2">
                  <DataTable
                    columns={commitColumns}
                    rows={filteredEvents.slice(0, 12).map((row) => ({
                      ...row,
                      timestamp: formatDate(row.timestamp),
                      attendance_pct:
                        row.attendance_pct === null || row.attendance_pct === undefined
                          ? "N/A"
                          : Number(row.attendance_pct).toFixed(2),
                    }))}
                    emptyMessage="No commit events matched the current search."
                  />
                </Panel>

                <Panel title="Top Developers">
                  <BarList items={topDevelopers} />
                </Panel>

                <Panel title="Top Repositories">
                  <BarList items={topRepositories} />
                </Panel>
              </div>
            </section>

            <section className="section-block" id="links">
              <div className="section-heading">
                <div>
                  <p className="section-kicker">Commit Linkage</p>
                  <h2>Linked commit IDs and readable commit names</h2>
                </div>
              </div>

              <div className="content-grid">
                <Panel title="Linked Commit Names" className="span-2">
                  <DataTable
                    columns={linkedCommitColumns}
                    rows={filteredLinkedCommitRows.slice(0, 20).map((row) => ({
                      ...row,
                      commit_id: row.commit_id ? String(row.commit_id).slice(0, 12) : "N/A",
                    }))}
                    emptyMessage="No linked commit names available yet."
                  />
                </Panel>

                <Panel title="Issue to Commit Links" className="span-2">
                  <div className="link-list">
                    {linkedCommitDetails.length ? (
                      linkedCommitDetails.map((issue) => (
                        <article key={issue.issue_id} className="link-card">
                          <div className="link-card-header">
                            <div>
                              <p className="link-label">{issue.issue_id}</p>
                              <h3>{issue.title}</h3>
                            </div>
                            <strong>{issue.commits.length} commits</strong>
                          </div>
                          <div className="chip-row">
                            {issue.commits.map((commit) => (
                              <span key={commit.commit_id} className="chip">
                                {commit.commit_id ? String(commit.commit_id).slice(0, 8) : "N/A"}  {commit.message}
                              </span>
                            ))}
                          </div>
                        </article>
                      ))
                    ) : (
                      <p className="empty-state">No linked commits stored yet.</p>
                    )}
                  </div>
                </Panel>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function StatCard({ label, value, detail }) {
  return (
    <article className="stat-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}

function Panel({ title, children, className = "" }) {
  const classes = className ? `panel ${className}` : "panel";

  return (
    <section className={classes}>
      <div className="panel-header">
        <h3>{title}</h3>
      </div>
      {children}
    </section>
  );
}

function BarList({ items }) {
  const maxValue = items.length ? Math.max(...items.map((item) => item.value)) : 1;

  return (
    <div className="bar-list">
      {items.length ? (
        items.map((item) => (
          <div key={item.label} className="bar-row">
            <div className="bar-meta">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(item.value / maxValue) * 100}%` }} />
            </div>
          </div>
        ))
      ) : (
        <p className="empty-state">No data available.</p>
      )}
    </div>
  );
}

function DataTable({ columns, rows, emptyMessage }) {
  if (!rows.length) {
    return <p className="empty-state">{emptyMessage}</p>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || row.issue_id || `${row.commit_id}-${index}`}>
              {columns.map((column) => (
                <td key={column.key}>{row[column.key] ?? "N/A"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function groupCounts(rows, key) {
  const counts = rows.reduce((accumulator, row) => {
    const label = row[key] || "Unknown";
    accumulator[label] = (accumulator[label] || 0) + 1;
    return accumulator;
  }, {});

  return Object.entries(counts)
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value);
}

function formatDate(value) {
  if (!value) {
    return "N/A";
  }

  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export default App;
