import { useEffect, useMemo, useRef, useState, startTransition } from "react";

const API_BASE_URL =
  import.meta.env.VITE_REQ_CODEMAPPING_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  "http://127.0.0.1:8000";
const JIRA_API_BASE_URL = import.meta.env.VITE_JIRA_API_URL || "";
const ESTIMATE_API_BASE_URL = import.meta.env.VITE_ESTIMATE_API_URL || "http://127.0.0.1:8001";
const RISK_API_BASE_URL = import.meta.env.VITE_RISK_API_URL || "http://127.0.0.1:8002";
const managerFilters = ["Current Sprint", "Platform Team", "All Modules"];

const issueColumns = [
  { key: "issue_id", label: "Issue" },
  { key: "title", label: "Requirement" },
  { key: "status", label: "Status" },
  { key: "priority", label: "Priority" },
  { key: "commits", label: "Linked Commits" },
];

const commitColumns = [
  { key: "timestamp", label: "Time" },
  { key: "author", label: "Developer" },
  { key: "message", label: "Commit" },
  { key: "repository_name", label: "Repository" },
  { key: "total_changes", label: "Changes" },
  { key: "impact_score", label: "Impact" },
];

const developerFocusColumns = [
  { key: "timestamp", label: "Time" },
  { key: "repository_name", label: "Repository" },
  { key: "message", label: "Commit" },
  { key: "total_changes", label: "Changes" },
];

const developerRequirementColumns = [
  { key: "issue_id", label: "Issue" },
  { key: "title", label: "Requirement" },
  { key: "status", label: "Status" },
  { key: "priority", label: "Priority" },
];

const issueCommitColumns = [
  { key: "timestamp", label: "Time" },
  { key: "author", label: "Developer" },
  { key: "repository_name", label: "Repository" },
  { key: "message", label: "Commit" },
  { key: "total_changes", label: "Changes" },
];

const landingPillars = [
  ["Intent Mapping", "Connect Jira requirements, commits, and code movement into one explainable story."],
  ["Effort Estimation", "Turn raw engineering activity into fair signals about actual effort and delivery."],
  ["Impact Scoring", "Show business-facing impact with language that managers and judges understand quickly."],
  ["Knowledge Risk", "Detect ownership gaps before they become delivery or onboarding bottlenecks."],
];

const landingHighlights = [
  { value: "Live Jira", label: "requirements flowing into one view" },
  { value: "Explainable", label: "signals managers can trust quickly" },
  { value: "Hackathon-ready", label: "clean story from hook to demo" },
];

const developerBreakdown = [
  { label: "Architectural", value: 40, tone: "cyan" },
  { label: "Functional Complexity", value: 30, tone: "purple" },
  { label: "Collaboration", value: 30, tone: "green" },
];

const developerTimeline = [
  { title: "Refactored Jira sync pagination", meta: "Today, 10:15", score: "+12 impact" },
  { title: "Linked 3 commits to DEV-142", meta: "Yesterday, 18:40", score: "+9 impact" },
  { title: "Reduced auth knowledge risk", meta: "Yesterday, 11:05", score: "+7 impact" },
];

function App() {
  const [route, setRoute] = useState(getRoute());
  const [events, setEvents] = useState([]);
  const [issues, setIssues] = useState([]);
  const [syncInfo, setSyncInfo] = useState(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedFilter, setSelectedFilter] = useState(managerFilters[0]);
  const [selectedReason, setSelectedReason] = useState(null);
  const [activeSearchSuggestion, setActiveSearchSuggestion] = useState(null);

  useEffect(() => {
    const onHashChange = () => startTransition(() => setRoute(getRoute()));
    window.addEventListener("hashchange", onHashChange);
    if (!window.location.hash) window.location.hash = "#/";
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    async function loadDashboard() {
      setLoading(true);
      setError("");
      try {
        const response = await fetch(`${API_BASE_URL}/api/dashboard`);
        if (!response.ok) throw new Error(`Backend request failed with ${response.status}`);
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

  const scopedEvents = useMemo(() => filterEventsByManagerView(events, selectedFilter), [events, selectedFilter]);
  const scopedIssues = useMemo(() => filterIssuesByManagerView(issues, scopedEvents, selectedFilter), [issues, scopedEvents, selectedFilter]);

  const filteredEvents = useMemo(
    () => filterRows(scopedEvents, query, ["message", "author", "author_email", "repository_name", "commit_id", "issue_id", "branch", "total_changes"]),
    [scopedEvents, query],
  );
  const filteredIssues = useMemo(
    () => filterRows(scopedIssues, query, ["issue_id", "title", "status", "priority", "project_key", "commits", "assignee_email", "reporter_email"]),
    [scopedIssues, query],
  );
  const searchSuggestions = useMemo(() => buildSearchSuggestions(scopedEvents, scopedIssues, query), [scopedEvents, scopedIssues, query]);
  const activeDeveloperFocus = useMemo(
    () => buildDeveloperFocus(activeSearchSuggestion, scopedEvents, scopedIssues),
    [activeSearchSuggestion, scopedEvents, scopedIssues],
  );
  const activeIssueFocus = useMemo(
    () => buildIssueFocus(activeSearchSuggestion, scopedEvents, scopedIssues),
    [activeSearchSuggestion, scopedEvents, scopedIssues],
  );

  const issueRows = useMemo(
    () =>
      filteredIssues.slice(0, 6).map((issue) => ({
        ...issue,
        commits: Array.isArray(issue.commits) && issue.commits.length ? issue.commits.join(", ") : "No linked commits",
      })),
    [filteredIssues],
  );

  const commitRows = useMemo(
    () =>
      filteredEvents.slice(0, 8).map((event) => ({
        ...event,
        timestamp: formatDate(event.timestamp),
        total_changes: Number(event.total_changes || 0),
        impact_score: `${clamp(42 + Number(event.total_changes || 0) / 3, 0, 99).toFixed(0)}`,
      })),
    [filteredEvents],
  );

  const totalChanges = useMemo(() => scopedEvents.reduce((sum, event) => sum + Number(event.total_changes || 0), 0), [scopedEvents]);
  const linkedIssues = useMemo(() => scopedIssues.filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0).length, [scopedIssues]);
  const avgAttendance = useMemo(() => average(scopedEvents.map((event) => Number(event.attendance_pct)).filter((value) => !Number.isNaN(value))), [scopedEvents]);

  const healthSignals = useMemo(
    () => [
      metricCard("Delivery Predictability", `${clamp(58 + linkedIssues * 4 + avgAttendance / 5, 0, 100).toFixed(0)}%`, "+8 this sprint", "Requirements are linking to shipped work with fewer blind spots.", "cyan", "Driven by traceability coverage, linked commits, and consistent contribution patterns."),
      metricCard("Business Value Delivered", `${clamp(62 + totalChanges / 25 + linkedIssues * 3, 0, 100).toFixed(0)} pts`, "+13 vs last sprint", "High-value requirements are getting clearer execution signals.", "purple", "Based on change volume, linked delivery events, and requirement activity."),
      metricCard("Knowledge Coverage", `${clamp(48 + scopedEvents.length * 2, 0, 100).toFixed(0)}%`, "2 modules at risk", "Expertise concentration is improving, but backend ownership is still narrow.", "green", "Calculated from contributor spread across repositories and repeated module ownership."),
      metricCard("Burnout Risk", `${clamp(65 - avgAttendance / 2 + Math.max(scopedEvents.length - 10, 0) * 1.8, 0, 100).toFixed(0)}%`, "1 alert needs action", "Sustained commit density suggests one team member may need rebalancing.", "amber", "Derived from activity clustering and uneven workload distribution."),
    ],
    [avgAttendance, scopedEvents.length, linkedIssues, totalChanges],
  );

  const repositoryBreakdown = useMemo(() => groupCounts(filteredEvents, "repository_name"), [filteredEvents]);
  const statusBreakdown = useMemo(() => groupCounts(filteredIssues, "status"), [filteredIssues]);
  const impactLeaderboard = useMemo(() => buildLeaderboard(filteredEvents), [filteredEvents]);
  const managerTrend = useMemo(() => buildManagerOverviewTrend(filteredEvents, filteredIssues), [filteredEvents, filteredIssues]);
  const workloadHeatmap = useMemo(() => buildRepositoryRisk(filteredEvents, filteredIssues), [filteredEvents, filteredIssues]);
  const managerEmpty = !loading && !error && !scopedEvents.length && !scopedIssues.length;

  return (
    <div className="app-shell">
      <TopNav route={route} />
      <main>
        {route === "manager" ? (
          <ManagerPage
            query={query}
            setQuery={setQuery}
            selectedFilter={selectedFilter}
            setSelectedFilter={setSelectedFilter}
            loading={loading}
            error={error}
            managerEmpty={managerEmpty}
            syncInfo={syncInfo}
            healthSignals={healthSignals}
            issueRows={issueRows}
            commitRows={commitRows}
            statusBreakdown={statusBreakdown}
            repositoryBreakdown={repositoryBreakdown}
            impactLeaderboard={impactLeaderboard}
            managerTrend={managerTrend}
            workloadHeatmap={workloadHeatmap}
            searchSuggestions={searchSuggestions}
            activeDeveloperFocus={activeDeveloperFocus}
            activeIssueFocus={activeIssueFocus}
            setActiveSearchSuggestion={setActiveSearchSuggestion}
            setSelectedReason={setSelectedReason}
          />
        ) : route === "intelligence" ? (
          <IntelligencePage
            issues={issues}
            events={events}
            syncInfo={syncInfo}
            loading={loading}
            error={error}
          />
        ) : route === "developer" ? (
          <DeveloperPage
            issues={issues}
            events={events}
            loading={loading}
            error={error}
          />
        ) : route === "risk" ? (
          <RiskPage />
        ) : route === "pricing" ? (
          <PricingPage />
        ) : route === "estimation" ? (
          <EstimationPage />
        ) : (
          <LandingPage />
        )}
      </main>
      {selectedReason ? <ExplainabilityModal card={selectedReason} onClose={() => setSelectedReason(null)} /> : null}
    </div>
  );
}

function TopNav({ route }) {
  const links = [
    { id: "landing", label: "Home", href: "#/" },
    { id: "intelligence", label: "Intelligence", href: "#/intelligence" },
    { id: "manager", label: "Manager", href: "#/manager" },
    { id: "developer", label: "Developer", href: "#/developer" },
    { id: "risk", label: "Risk", href: "#/risk" },
    { id: "estimation", label: "Estimation", href: "#/estimation" },
    { id: "pricing", label: "Pricing", href: "#/pricing" },
  ];

  return (
    <header className="topbar">
      <a className="brand" href="#/">
        <span className="brand-mark">DH</span>
        <div>
          <strong>DevHouse</strong>
          <span>Designed for Tech Lead Manager (TLM)</span>
        </div>
      </a>
      <nav className="topnav">
        {links.map((item) => (
          <a key={item.id} className={route === item.id ? "nav-link active" : "nav-link"} href={item.href}>
            {item.label}
          </a>
        ))}
      </nav>
    </header>
  );
}

function LandingPage() {
  const storyReveal = useRevealOnView();
  const pillarsReveal = useRevealOnView();
  const landingRef = useRef(null);
  const heroRef = useRef(null);
  const heroProgress = useHeroScrollProgress(landingRef);
  const backgroundVideoRef = useRef(null);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const { isReady, loadProgress, reducedMotion } = useCinematicHeroVideo({ videoRef: backgroundVideoRef });
  const heroOffset = Math.min(heroProgress * 90, 72);
  const cardOffset = Math.min(heroProgress * 72, 56);
  const ringOffset = Math.min(heroProgress * 48, 34);
  const headlineOffset = heroProgress * -18;
  const stripOffset = Math.min(heroProgress * 26, 18);
  const frameOffset = heroProgress * -26;

  return (
    <div ref={landingRef} className="page landing-page cinematic-page">
      <div className="landing-cinematic-shell">
        {!isReady ? <HeroLoader progress={loadProgress} /> : null}

        <div className="hero-sticky-shell">
          <video
            ref={backgroundVideoRef}
            className="hero-background-video"
            src="/media/Modify_the_existing_202603312331.mp4"
            preload="auto"
            autoPlay
            muted={!audioEnabled}
            playsInline
            controls={false}
            aria-hidden="true"
          />

          <div className="hero-canvas-fallback" style={{ backgroundImage: "url('/media/hero-sequence.webp')" }} aria-hidden="true" />

          <div className="hero-ambient-layer" aria-hidden="true">
            <div className="parallax-orb orb-a" style={{ transform: `translate3d(0, ${heroProgress * -34}px, 0)` }} />
            <div className="parallax-orb orb-b" style={{ transform: `translate3d(0, ${heroProgress * 26}px, 0)` }} />
            <div className="signal-arc arc-one" style={{ transform: `translate3d(0, ${heroProgress * -18}px, 0) rotate(${heroProgress * 8}deg)` }} />
            <div className="signal-arc arc-two" style={{ transform: `translate3d(0, ${heroProgress * 12}px, 0) rotate(${-heroProgress * 7}deg)` }} />
            <div className="data-stream stream-one" style={{ transform: `translate3d(${heroProgress * 20}px, ${heroProgress * -10}px, 0)` }} />
            <div className="data-stream stream-two" style={{ transform: `translate3d(${-heroProgress * 16}px, ${heroProgress * 12}px, 0)` }} />
          </div>
        </div>

      </div>

      <section ref={heroRef} className="hero-cinematic-section">
        <div className="hero-content-grid hero parallax-stage">
          <div className="parallax-frame" style={{ transform: `translate3d(0, ${frameOffset}px, 0)` }} />
            <div className="hero-copy hero-copy-cinematic" style={{ transform: `translate3d(0, ${headlineOffset}px, 0)` }}>
              <p className="eyebrow">Built for high-stakes delivery teams</p>
              <h1 className="hero-title-strong">Make engineering impact visible, explainable, and impossible to ignore.</h1>
              <p className="hero-text">We map requirements, commits, expertise, and delivery signals into one decision-ready view for judges, CTOs, and engineering managers.</p>
              <div className="cta-row">
                <a className="button primary" href="#/manager">See Manager Dashboard</a>
                <a className="button secondary" href="#/developer">View Developer Experience</a>
                <button
                  type="button"
                  className="button secondary audio-toggle"
                  onClick={async () => {
                    const video = backgroundVideoRef.current;
                    if (!video) return;
                    if (audioEnabled) {
                      video.muted = true;
                      setAudioEnabled(false);
                      return;
                    }
                    try {
                      video.muted = false;
                      await video.play();
                      setAudioEnabled(true);
                    } catch {
                      video.muted = true;
                      setAudioEnabled(false);
                    }
                  }}
                >
                  {audioEnabled ? "Mute Audio" : "Enable Audio"}
                </button>
              </div>
              <div className="problem-strip">
                <span className="problem-label">Problem Statement</span>
                <p>Teams ship code every day, but leaders still struggle to measure true impact, trace delivery, and detect knowledge risk before deadlines slip.</p>
              </div>
              <div className="premium-strip" style={{ transform: `translate3d(0, ${stripOffset}px, 0)` }}>
                <span>Traceability</span>
                <span>Impact Intelligence</span>
                <span>Knowledge Risk</span>
                <span>Delivery Confidence</span>
              </div>
              <div className="landing-highlight-row">
                {landingHighlights.map((item) => (
                  <article key={item.label} className="landing-highlight-card">
                    <strong>{item.value}</strong>
                    <span>{item.label}</span>
                  </article>
                ))}
              </div>
            </div>

          <div className="hero-visual hero-product-visual" style={{ transform: `translate3d(0, ${heroOffset}px, 0)` }}>
            <div className="laptop-shell" style={{ transform: `translate3d(0, ${cardOffset * -1}px, 0) rotate(${reducedMotion ? 0 : -7 + heroProgress * 14}deg)` }}>
              <div className="laptop-screen mock-window parallax-card">
                <div className="window-top"><span /><span /><span /></div>
                <div className="mock-kpis">
                  <MetricMini label="Value" value="84" tone="cyan" />
                  <MetricMini label="Traceability" value="76" tone="purple" />
                  <MetricMini label="Risk" value="32" tone="green" />
                </div>
                <LineTrend items={[{ label: "W1", value: 32 }, { label: "W2", value: 47 }, { label: "W3", value: 59 }, { label: "W4", value: 73 }]} compact />
              </div>
              <div className="laptop-base" />
            </div>

            <div className="hero-floating-stack" style={{ transform: `translate3d(0, ${ringOffset}px, 0)` }}>
              <div className="mock-window developer-preview parallax-card secondary terminal-panel">
                <div className="terminal-head">
                  <span>terminal</span>
                  <span>active</span>
                </div>
                <div className="terminal-lines">
                  <div className="terminal-line-item"><span className="terminal-dot" /> <span>traceability sync live</span></div>
                  <div className="terminal-line-item"><span className="terminal-dot" /> <span>impact graph connected</span></div>
                  <div className="terminal-line-item"><span className="terminal-dot" /> <span>workload alerts calibrated</span></div>
                </div>
              </div>
              <div className="mock-window developer-preview parallax-card secondary insight-panel">
                <div className="insight-panel-top">
                  <div className="developer-score-ring"><strong>87</strong><span>Impact Score</span></div>
                </div>
                <div className="insight-breakdown">
                  <p className="insight-label">Contribution Breakdown</p>
                  <ContributionBreakdown items={developerBreakdown} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section ref={pillarsReveal.ref} className={`landing-grid reveal-block ${pillarsReveal.isVisible ? "is-visible" : ""}`}>
        <SectionHead eyebrow="Solution Highlights" title="One product story, three winning demo moments" />
        <div className="pillar-grid">
          {landingPillars.map(([title, text], index) => (
            <article
              key={title}
              className={`glass-card pillar-card parallax-card reveal-card ${pillarsReveal.isVisible ? "is-visible" : ""}`}
              style={{
                transform: `translate3d(0, ${Math.min(heroProgress * 42 * (index + 1), 18 + index * 6)}px, 0)`,
                transitionDelay: `${index * 90}ms`,
              }}
            >
              <div className="icon-chip">{title.slice(0, 1)}</div>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>

      <section ref={storyReveal.ref} className={`landing-grid reveal-block ${storyReveal.isVisible ? "is-visible" : ""}`}>
        <SectionHead eyebrow="Demo Flow" title="Built to win attention in the first minute" />
        <div className="pillar-grid story-grid">
          {[
            ["Hook Judges Fast", "Open with a clear problem, sleek visuals, and a story that feels product-ready in seconds."],
            ["Give Managers Clarity", "Show impact, predictability, and risk in business language instead of raw engineering noise."],
            ["Respect Developers", "Make the developer experience transparent, encouraging, and useful rather than invasive."],
            ["End With Confidence", "Tie the product together with explainability, live data, and a clean visual system."],
          ].map(([title, text], index) => (
            <article key={title} className={`glass-card pillar-card reveal-card ${storyReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: `${index * 110}ms` }}>
              <div className="icon-chip">{index + 1}</div>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function ManagerPage({ query, setQuery, selectedFilter, setSelectedFilter, loading, error, managerEmpty, syncInfo, healthSignals, issueRows, commitRows, statusBreakdown, repositoryBreakdown, impactLeaderboard, managerTrend, workloadHeatmap, searchSuggestions, activeDeveloperFocus, activeIssueFocus, setActiveSearchSuggestion, setSelectedReason }) {
  const heroReveal = useRevealOnView();
  const kpiReveal = useRevealOnView();
  const gridReveal = useRevealOnView();

  return (
    <div className="page dashboard-page">
      <section ref={heroReveal.ref} className={`dashboard-hero dashboard-stage reveal-block ${heroReveal.isVisible ? "is-visible" : ""}`}>
        <div className="parallax-orb orb-c" />
        <div>
          <p className="eyebrow">Manager Dashboard</p>
          <h1>Turn engineering activity into executive decisions.</h1>
          <p className="hero-text narrow">See who is creating value, where delivery is at risk, and why your impact scores are rising or falling.</p>
        </div>
        <div className="toolbar dashboard-float">
          <label className="search-input">
            <span>Search delivery signals</span>
            <input
              value={query}
              onChange={(event) => {
                const nextValue = event.target.value;
                setQuery(nextValue);
                if (!nextValue.trim()) setActiveSearchSuggestion(null);
              }}
              placeholder="Search by issue, commit, repository, or developer"
            />
            {query.trim() ? (
              <div className="search-suggestions">
                {searchSuggestions.length ? (
                  searchSuggestions.map((item) => (
                    <button
                      key={`${item.type}-${item.value}`}
                      type="button"
                      className={`search-suggestion ${(activeDeveloperFocus?.name === item.label || activeIssueFocus?.issueId === item.value) ? "active" : ""}`}
                      onClick={() => {
                        setQuery(item.value);
                        setActiveSearchSuggestion(item);
                      }}
                    >
                      <span className="search-suggestion-type">{item.type}</span>
                      <strong>{item.label}</strong>
                      <small>{item.meta}</small>
                    </button>
                  ))
                ) : (
                  <div className="search-suggestion empty">
                    <strong>No matching suggestions</strong>
                    <small>Try issue ID, developer name, repository, branch, or commit ID.</small>
                  </div>
                )}
              </div>
            ) : null}
          </label>
          <div className="filter-pills">
            {managerFilters.map((filter) => (
              <button key={filter} type="button" className={selectedFilter === filter ? "pill active" : "pill"} onClick={() => setSelectedFilter(filter)}>
                {filter}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section ref={kpiReveal.ref} className={`kpi-grid reveal-block ${kpiReveal.isVisible ? "is-visible" : ""}`}>
        {healthSignals.map((card, index) => (
          <button
            key={card.title}
            type="button"
            className={`kpi-card reveal-card ${kpiReveal.isVisible ? "is-visible" : ""} ${card.tone}`}
            style={{ transitionDelay: `${index * 80}ms` }}
            onClick={() => setSelectedReason(card)}
          >
            <div className="kpi-topline"><span>{card.title}</span><span className="why-link">Why?</span></div>
            <strong>{card.value}</strong>
            <p>{card.description}</p>
            <small>{card.change}</small>
          </button>
        ))}
      </section>

      {syncInfo ? <section className="status-banner glass-card reveal-card is-visible"><strong>Live update</strong><span>{syncInfo.linked_commits || 0} linked commits across {syncInfo.matched_issues || 0} requirements during the latest refresh.</span></section> : null}
      {loading ? <StateCard title="Loading manager view" text="Pulling requirements, commit events, and traceability signals from the backend." className="reveal-card is-visible" /> : null}
      {error ? <StateCard title="Backend not reachable" text={`${error}. The design is ready, and live data will appear once the API is running.`} error className="reveal-card is-visible" /> : null}
      {managerEmpty ? <StateCard title="No live data yet" text="Connect your services and telemetry feed to populate this dashboard with real delivery signals." className="reveal-card is-visible" /> : null}

      {activeDeveloperFocus ? (
        <section className="dashboard-grid manager-focus-grid reveal-block is-visible">
          <PanelCard title={`${activeDeveloperFocus.name} Contribution Focus`} subtitle={`${activeDeveloperFocus.totalCommits} commits across ${activeDeveloperFocus.repositories.length} repositories in the current scope`} className="span-2 reveal-card is-visible">
            <div className="manager-focus-hero">
              <div className="focus-metrics">
                <MetricMini label="Code Changes" value={activeDeveloperFocus.totalChanges} tone="cyan" />
                <MetricMini label="Linked Requirements" value={activeDeveloperFocus.linkedRequirements} tone="purple" />
                <MetricMini label="Impact Score" value={activeDeveloperFocus.impactScore} tone="green" />
              </div>
              <p>{activeDeveloperFocus.summary}</p>
            </div>
          </PanelCard>
          <PanelCard title="Individual Contribution Trend" subtitle="Commit activity over the latest delivery window" className="reveal-card is-visible">
            <LineTrend items={activeDeveloperFocus.trend} compact />
          </PanelCard>
          <PanelCard title="Repositories Worked" subtitle="Where this developer is contributing" className="reveal-card is-visible">
            <BarList items={activeDeveloperFocus.repositories} />
          </PanelCard>
          <PanelCard title="Recent Commits" subtitle="Latest work from this developer" className="span-2 reveal-card is-visible">
            <DataTable columns={developerFocusColumns} rows={activeDeveloperFocus.commitRows} emptyMessage="No recent commits for this developer in the selected scope." />
          </PanelCard>
          <PanelCard title="Requirements Touched" subtitle="Requirements linked to this developer's recent activity" className="span-2 reveal-card is-visible">
            <DataTable columns={developerRequirementColumns} rows={activeDeveloperFocus.requirementRows} emptyMessage="No linked requirements found for this developer in the selected scope." />
          </PanelCard>
        </section>
      ) : null}

      {activeIssueFocus ? (
        <section className="dashboard-grid manager-focus-grid reveal-block is-visible">
          <PanelCard title={`${activeIssueFocus.issueId} Requirement Focus`} subtitle={`${activeIssueFocus.commitCount} linked commits across ${activeIssueFocus.repositories.length} repositories`} className="span-2 reveal-card is-visible">
            <div className="manager-focus-hero">
              <div className="focus-metrics">
                <MetricMini label="Status" value={activeIssueFocus.status} tone="cyan" />
                <MetricMini label="Priority" value={activeIssueFocus.priority} tone="purple" />
                <MetricMini label="Code Changes" value={activeIssueFocus.totalChanges} tone="green" />
              </div>
              <p>{activeIssueFocus.summary}</p>
            </div>
          </PanelCard>
          <PanelCard title="Developer Contribution Split" subtitle="Who contributed how much to this requirement" className="reveal-card is-visible">
            <BarList items={activeIssueFocus.developerContribution} />
          </PanelCard>
          <PanelCard title="Repository Spread" subtitle="Where this requirement was implemented" className="reveal-card is-visible">
            <BarList items={activeIssueFocus.repositories} />
          </PanelCard>
          <PanelCard title="Related Commits" subtitle="Recent delivery activity linked to this requirement" className="span-2 reveal-card is-visible">
            <DataTable columns={issueCommitColumns} rows={activeIssueFocus.commitRows} emptyMessage="No linked commits found for this requirement in the selected scope." />
          </PanelCard>
        </section>
      ) : null}

      <section ref={gridReveal.ref} className={`dashboard-grid reveal-block ${gridReveal.isVisible ? "is-visible" : ""}`}>
        <PanelCard title="Team Overview Trend" subtitle={`Live delivery signal for ${selectedFilter.toLowerCase()}`} className={`span-2 reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "0ms" }}><LineTrend items={managerTrend} /></PanelCard>
        <PanelCard title="Impact Leaderboard" subtitle="Explainable, manager-friendly ranking" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "70ms" }}><Leaderboard items={impactLeaderboard} /></PanelCard>
        <PanelCard title="Workload Heatmap" subtitle="Spot overload before it becomes burnout" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "120ms" }}><HeatBars items={workloadHeatmap} /></PanelCard>
        <PanelCard title="Requirement Traceability" subtitle="How clearly work maps back to requirements" className={`span-2 reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "160ms" }}><DataTable columns={issueColumns} rows={issueRows} emptyMessage="No issues match the current filters." /></PanelCard>
        <PanelCard title="Recent Delivery Activity" subtitle="Latest commits and impact indicators" className={`span-2 reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "220ms" }}><DataTable columns={commitColumns} rows={commitRows} emptyMessage="No commit activity matched the current filters." /></PanelCard>
        <PanelCard title="Requirement Status" subtitle="Track delivery flow" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "260ms" }}><BarList items={statusBreakdown} /></PanelCard>
        <PanelCard title="Repository Distribution" subtitle="Where work is happening" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "300ms" }}><BarList items={repositoryBreakdown.slice(0, 5)} /></PanelCard>
      </section>
    </div>
  );
}

function DeveloperPage({ issues, events, loading, error }) {
  const heroReveal = useRevealOnView();
  const gridReveal = useRevealOnView();
  const commitByDeveloper = groupCounts(events, "author").slice(0, 5);
  const requirementStatus = groupCounts(issues, "status").slice(0, 5);
  const linkedRequirements = issues.filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0).length;
  const requirementCoverage = [
    { label: "Linked Requirements", value: linkedRequirements },
    { label: "Unlinked Requirements", value: Math.max(issues.length - linkedRequirements, 0) },
  ];
  const commitTrend = buildDailyCommitCountTrend(events);
  const liveTimeline = buildDeveloperTimelineClean(events);
  const totalCommits = events.length;
  const activeDevelopers = new Set(events.map((event) => event.author).filter(Boolean)).size;
  const developerImpactScore = clamp(52 + totalCommits * 2 + linkedRequirements * 3, 0, 99);
  const liveImpactBreakdown = buildDeveloperImpactBreakdown(events, issues);
  const radarItems = buildDeveloperRadar(events, issues);

  return (
    <div className="page dashboard-page">
      <section ref={heroReveal.ref} className={`dashboard-hero developer-hero dashboard-stage reveal-block ${heroReveal.isVisible ? "is-visible" : ""}`}>
        <div className="parallax-orb orb-d" />
        <div>
          <p className="eyebrow">Developer Dashboard</p>
          <h1>Your impact is visible, fair, and built to help you grow.</h1>
          <p className="hero-text narrow">This view now uses live database-backed commit and requirement data to show contribution patterns without turning work into surveillance.</p>
        </div>
        <div className="developer-spotlight glass-card dashboard-float reveal-card is-visible">
          <span className="spotlight-label">Personal Impact Score</span>
          <strong>{Math.round(developerImpactScore)}</strong>
          <p>{loading ? "Loading activity..." : `${totalCommits} commits, ${linkedRequirements} linked requirements, and ${activeDevelopers || 1} active contributors in the current dataset.`}</p>
        </div>
      </section>

      {error ? <StateCard title="Backend not reachable" text={`${error}. Developer graphs will populate once live data is available.`} error className="reveal-card is-visible" /> : null}

      <section ref={gridReveal.ref} className={`dashboard-grid reveal-block ${gridReveal.isVisible ? "is-visible" : ""}`}>
        <PanelCard title="Explainable Impact Breakdown" subtitle="A transparent view of what drove your score" className={`span-2 reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "0ms" }}><ContributionBreakdown items={liveImpactBreakdown} /></PanelCard>
        <PanelCard title="Workload Balance" subtitle="Healthy effort with one mild overtime warning" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "70ms" }}><Meter /></PanelCard>
        <PanelCard title="Commits by Developer" subtitle="How many commits are coming from each contributor" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "120ms" }}><BarList items={commitByDeveloper} /></PanelCard>
        <PanelCard title="Contribution Trend" subtitle="Commit volume from the database over time" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "170ms" }}><LineTrend items={commitTrend} /></PanelCard>
        <PanelCard title="Requirement Status" subtitle="How requirements are moving right now" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "220ms" }}><BarList items={requirementStatus} /></PanelCard>
        <PanelCard title="Requirement Coverage" subtitle="Linked versus unlinked requirement evidence" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "250ms" }}><BarList items={requirementCoverage} /></PanelCard>
        <PanelCard title="Skill Radar" subtitle="Live-derived signal from delivery data" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "280ms" }}><RadarList items={radarItems} /></PanelCard>
        <PanelCard title="Growth Recommendations" subtitle="Actionable next steps from current activity" className={`reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "310ms" }}><SimpleList items={buildGrowthRecommendations(events, issues, linkedRequirements)} /></PanelCard>
        <PanelCard title="My Activity Timeline" subtitle="Recent database-backed delivery activity" className={`span-2 reveal-card ${gridReveal.isVisible ? "is-visible" : ""}`} style={{ transitionDelay: "340ms" }}><Timeline items={liveTimeline} /></PanelCard>
      </section>
    </div>
  );
}

function IntelligencePage({ issues, events, syncInfo, loading, error }) {
  const heroReveal = useRevealOnView();
  const gridReveal = useRevealOnView();
  const [scopeReduction, setScopeReduction] = useState(10);
  const [addedDevelopers, setAddedDevelopers] = useState(1);
  const [riskRequirements, setRiskRequirements] = useState([]);
  const [riskLoading, setRiskLoading] = useState(true);
  const [riskError, setRiskError] = useState("");

  useEffect(() => {
    let active = true;
    async function loadRiskRequirements() {
      setRiskLoading(true);
      setRiskError("");
      try {
        const response = await fetch(`${RISK_API_BASE_URL}/api/risk/requirements?limit=8`);
        if (!response.ok) throw new Error(`Risk engine request failed with ${response.status}`);
        const payload = await response.json();
        if (!active) return;
        setRiskRequirements(Array.isArray(payload.requirements) ? payload.requirements : []);
      } catch (fetchError) {
        if (!active) return;
        setRiskError(fetchError.message || "Failed to load requirement risk data");
      } finally {
        if (active) setRiskLoading(false);
      }
    }
    loadRiskRequirements();
    return () => {
      active = false;
    };
  }, []);

  const linkedIssues = issues.filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0).length;
  const totalChanges = events.reduce((sum, event) => sum + Number(event.total_changes || 0), 0);
  const avgAttendance = average(events.map((event) => Number(event.attendance_pct)).filter((value) => !Number.isNaN(value)));
  const contributorCount = new Set(events.map((event) => event.author).filter(Boolean)).size;
  const baseRisk = clamp(72 - linkedIssues * 5 + Math.max(events.length - 10, 0) * 1.6 + (60 - avgAttendance) / 3, 14, 94);
  const effortOverrun = clamp(baseRisk - 8 + events.length * 0.9, 10, 97);
  const delayProbability = clamp(baseRisk + Math.max(issues.length - linkedIssues, 0) * 3.5, 12, 98);
  const confidence = clamp(48 + linkedIssues * 7 + contributorCount * 3, 28, 96);

  const trendItems = buildDailyTrend(events, issues);
  const repositoryRisk = buildRepositoryRisk(events, issues);
  const riskFactors = buildRiskFactors({ issues, events, linkedIssues, avgAttendance, contributorCount });
  const actionCards = buildPrescriptions({ issues, events, linkedIssues, baseRisk, repositoryRisk });
  const alerts = buildAlerts({ baseRisk, delayProbability, repositoryRisk, linkedIssues, issues, syncInfo });
  const timelineItems = buildDecisionTimeline(events, issues);
  const requirementPredictions = buildRequirementPredictions(issues, events);
  const liveRiskRows = useMemo(
    () =>
      riskRequirements.map((item) => ({
        issue_id: item.requirement_id,
        risk: `${Math.round(Number(item.risk_score || 0) * 100)}%`,
        level: item.risk_level || "Unknown",
        due_date: item.due_date ? formatDate(item.due_date) : "No due date",
        reason: Array.isArray(item.reasons) && item.reasons.length ? item.reasons[0] : "No explanation yet",
        next_step: Array.isArray(item.recommendations) && item.recommendations.length ? item.recommendations[0] : "No recommendation yet",
      })),
    [riskRequirements],
  );
  const highestLiveRisk = riskRequirements[0] || null;
  const developerPredictions = buildDeveloperPredictions(events, issues);
  const forecastCards = buildForecastCards({ issues, events, linkedIssues, baseRisk, delayProbability, confidence });
  const topRequirements = buildTopRequirementSignals(issues, events);
  const topCommitters = groupCounts(events, "author")
    .slice(0, 5)
    .map((item) => ({
      developer: item.label,
      commits: item.value,
      forecast: item.value >= 3 ? "High activity contributor" : "Steady contribution pattern",
    }));
  const issueInsightRows = issues.slice(0, 6).map((issue) => ({
    issue_id: issue.issue_id,
    status: issue.status || "Unknown",
    priority: issue.priority || "Unknown",
    commits: Array.isArray(issue.commits) ? issue.commits.length : 0,
  }));

  const simulatedRisk = clamp(baseRisk - scopeReduction * 0.7 - addedDevelopers * 4.5, 8, 99);
  const simulatedDelay = clamp(delayProbability - scopeReduction * 0.8 - addedDevelopers * 5.2, 6, 99);
  const projectedDeliveryDays = Math.max(3, Math.round(14 + delayProbability / 8 - scopeReduction / 6 - addedDevelopers));

  return (
    <div className="page dashboard-page intelligence-page">
      <section ref={heroReveal.ref} className={`dashboard-hero dashboard-stage intelligence-hero reveal-block ${heroReveal.isVisible ? "is-visible" : ""}`}>
        <div className="parallax-orb orb-c" />
        <div>
          <p className="eyebrow">Decision Intelligence</p>
          <h1>Make predictive analytics feel like clear, guided decision-making.</h1>
          <p className="hero-text narrow">This page translates your backend intelligence into a frontend story that answers what will happen, why it will happen, and what should happen next.</p>
        </div>
        <div className="intelligence-summary glass-card dashboard-float reveal-card parallax-card is-visible">
          <span className="spotlight-label">Frontend Mission</span>
          <strong>Prediction + Explanation + Prescription</strong>
          <p>{loading ? "Loading live delivery signals..." : `Using ${issues.length} requirements, ${events.length} delivery events, and ${totalChanges} tracked code changes to drive the view.`}</p>
        </div>
      </section>

      <section className="intelligence-pillars">
        <article className="intelligence-pill parallax-card">
          <span>1</span>
          <strong>What will happen?</strong>
          <p>Prediction</p>
        </article>
        <article className="intelligence-pill parallax-card">
          <span>2</span>
          <strong>Why will it happen?</strong>
          <p>Explanation</p>
        </article>
        <article className="intelligence-pill parallax-card">
          <span>3</span>
          <strong>What should I do?</strong>
          <p>Prescription</p>
        </article>
      </section>

      <section className="intelligence-top-grid">
        <PanelCard title="Live Requirement Signals" subtitle="Requirements currently most active or at risk" className="reveal-card parallax-card is-visible">
          <DataTable
            columns={[
              { key: "issue_id", label: "Issue" },
              { key: "status", label: "Status" },
              { key: "priority", label: "Priority" },
              { key: "commits", label: "Commits" },
            ]}
            rows={topRequirements}
            emptyMessage="No requirements available yet."
          />
        </PanelCard>
        <PanelCard title="Highest Commit Contributors" subtitle="Developers with the most commits in the current dataset" className="reveal-card parallax-card is-visible">
          <DataTable
            columns={[
              { key: "developer", label: "Developer" },
              { key: "commits", label: "Commits" },
              { key: "forecast", label: "Signal" },
            ]}
            rows={topCommitters}
            emptyMessage="No commit activity available yet."
          />
        </PanelCard>
      </section>

      {error ? <StateCard title="Backend not reachable" text={`${error}. Intelligence cards will populate once live data is available.`} error className="reveal-card parallax-card is-visible" /> : null}

      <section ref={gridReveal.ref} className={`dashboard-grid intelligence-grid reveal-block ${gridReveal.isVisible ? "is-visible" : ""}`}>
        <PanelCard title="Prediction Dashboard" subtitle="At-a-glance forecast" className={`span-2 reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <div className="intelligence-metric-grid">
            <PredictionMetric label="Risk Score" value={`${Math.round(baseRisk)}`} tone={baseRisk > 65 ? "amber" : baseRisk > 40 ? "purple" : "green"} help="Overall delivery risk derived from traceability, workload concentration, and activity pressure." />
            <PredictionMetric label="Effort Overrun" value={`${Math.round(effortOverrun)}%`} tone="purple" help="Probability that current execution patterns run beyond expected effort." />
            <PredictionMetric label="Delay Prediction" value={`${Math.round(delayProbability)}%`} tone="amber" help="Likelihood of milestone slippage if current patterns continue." />
            <PredictionMetric label="Confidence" value={`${Math.round(confidence)}%`} tone="green" help="How strong the system's signal is based on available linked activity." />
          </div>
        </PanelCard>

        <PanelCard title="Risk Trend" subtitle="How the signal is evolving" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <LineTrend items={trendItems} />
        </PanelCard>

        <PanelCard title="Forecast Summary" subtitle="Predictions from live database patterns" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <PredictionSummary items={forecastCards} />
        </PanelCard>

        <PanelCard title="Live Risk Engine" subtitle="Requirement risk scored by the new backend engine" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          {riskError ? (
            <p className="empty-state">{riskError}. Make sure the Risk Engine is running at {RISK_API_BASE_URL}.</p>
          ) : riskLoading ? (
            <p className="empty-state">Scoring requirements with the live risk engine...</p>
          ) : highestLiveRisk ? (
            <div className="prediction-summary-card">
              <strong>{highestLiveRisk.requirement_id}</strong>
              <p>{highestLiveRisk.risk_level} risk at {Math.round(Number(highestLiveRisk.risk_score || 0) * 100)}%.</p>
              <p>{Array.isArray(highestLiveRisk.reasons) && highestLiveRisk.reasons.length ? highestLiveRisk.reasons[0] : "No explanation yet."}</p>
            </div>
          ) : (
            <p className="empty-state">No live risk results available yet.</p>
          )}
        </PanelCard>

        <PanelCard title="Risk Breakdown Panel" subtitle="Why risk is high" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <ContributionBreakdown items={riskFactors} />
        </PanelCard>

        <PanelCard title="Module Heatmap" subtitle="Where instability is building" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <HeatBars items={repositoryRisk} />
        </PanelCard>

        <PanelCard title="Prescriptive Actions Panel" subtitle="What the team should do next" className={`span-2 reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <ActionCardList items={actionCards} />
        </PanelCard>

        <PanelCard title="Predicted At-Risk Requirements" subtitle="Requirements most likely to slip or need intervention" className={`span-2 reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <DataTable
            columns={[
              { key: "issue_id", label: "Issue" },
              { key: "risk", label: "Risk" },
              { key: "level", label: "Level" },
              { key: "due_date", label: "Due Date" },
              { key: "reason", label: "Why" },
              { key: "next_step", label: "Recommended Action" },
            ]}
            rows={liveRiskRows.length ? liveRiskRows : requirementPredictions}
            emptyMessage={riskLoading ? "Loading live requirement predictions..." : "No requirement predictions available yet."}
          />
        </PanelCard>

        <PanelCard title="What-if Simulation" subtitle="Instant scenario planning" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <SimulationCard
            scopeReduction={scopeReduction}
            setScopeReduction={setScopeReduction}
            addedDevelopers={addedDevelopers}
            setAddedDevelopers={setAddedDevelopers}
            simulatedRisk={simulatedRisk}
            simulatedDelay={simulatedDelay}
            projectedDeliveryDays={projectedDeliveryDays}
          />
        </PanelCard>

        <PanelCard title="Developer and Module Insights" subtitle="Who and what is carrying the load" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <BarList items={groupCounts(events, "author").slice(0, 5)} />
        </PanelCard>

        <PanelCard title="Developer Forecast" subtitle="Who may need support next" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <DataTable
            columns={[
              { key: "developer", label: "Developer" },
              { key: "commits", label: "Commits" },
              { key: "risk", label: "Load Risk" },
              { key: "forecast", label: "Prediction" },
            ]}
            rows={developerPredictions}
            emptyMessage="No developer forecast data is available yet."
          />
        </PanelCard>

        <PanelCard title="Smart Alerts" subtitle="Signals that need attention" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <SimpleList items={alerts} />
        </PanelCard>

        <PanelCard title="Decision Timeline" subtitle="Recent system-relevant activity" className={`span-2 reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <Timeline items={timelineItems} />
        </PanelCard>

        <PanelCard title="Requirement Snapshot" subtitle="Live linked issue view" className={`span-2 reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <DataTable
            columns={[
              { key: "issue_id", label: "Issue" },
              { key: "status", label: "Status" },
              { key: "priority", label: "Priority" },
              { key: "commits", label: "Links" },
            ]}
            rows={issueInsightRows}
            emptyMessage="No requirement data is available yet."
          />
        </PanelCard>
      </section>
    </div>
  );
}

function PricingPage() {
  const heroReveal = useRevealOnView();
  const gridReveal = useRevealOnView();

  const plans = [
    {
      name: "Starter Pilot",
      price: "$2,500 - $4,000",
      subtitle: "Best for first-time customers validating DevIQ on a limited scope.",
      includes: [
        "6-8 week pilot",
        "Risk monitoring for selected features",
        "Silent Risk detection",
        "Intervention recommendations",
        "Basic simulation scenarios",
        "Setup and workflow mapping",
        "Integration and configuration support",
        "Monitoring and support",
        "End-of-pilot summary",
      ],
      bestFor: [
        "Early design partners",
        "Small to mid-sized teams",
        "Companies wanting proof of value before rollout",
      ],
      breakdown: [
        "Platform access and hosting: $300-$500",
        "Setup and workflow mapping: $500-$750",
        "Integration and configuration: $500-$750",
        "Infrastructure and storage: $200-$500",
        "Monitoring and support: $500-$750",
        "Reporting and pilot summary: $300-$500",
      ],
      cta: "Start Pilot",
      featured: false,
    },
    {
      name: "Growth",
      price: "$24 / engineer / month",
      subtitle: "For teams that want continuous delivery-risk monitoring.",
      includes: [
        "Predictive delivery risk scoring",
        "Silent Risk, Burnout, and Refactoring Spiral signals",
        "Feature-level risk views",
        "Recommended interventions",
        "Simulation workflows",
        "Knowledge continuity insights",
        "Manager dashboard",
        "Standard support",
      ],
      bestFor: [
        "Growing engineering organizations",
        "Teams with recurring delivery pressure",
        "Leaders who need predictable execution",
      ],
      breakdown: [],
      cta: "Start Subscription",
      featured: true,
    },
    {
      name: "Enterprise",
      price: "Custom Pricing",
      subtitle: "For organizations that need broader visibility, governance, and integration depth.",
      includes: [
        "Everything in Growth",
        "Portfolio-wide risk visibility",
        "Advanced simulation workflows",
        "Custom connectors",
        "Governance and audit controls",
        "Executive reporting",
        "Priority support",
        "Dedicated onboarding",
        "Custom rollout planning",
      ],
      bestFor: [
        "Large engineering organizations",
        "Multi-team and multi-repo environments",
        "Companies with stricter process and reporting needs",
      ],
      breakdown: [],
      cta: "Contact Sales",
      featured: false,
    },
  ];

  const includedInEveryPlan = [
    "Risk -> Why -> Action -> Simulation workflow",
    "Feature-level delivery risk visibility",
    "Explainable recommendations",
    "Evidence-backed risk factors",
    "Knowledge continuity context",
    "Ongoing product improvements",
  ];

  const faqs = [
    {
      q: "Is DevIQ subscription-based?",
      a: "Yes. DevIQ is sold as a subscription product. Larger customers may begin with a pilot before moving to an annual subscription.",
    },
    {
      q: "Do all customers need a pilot first?",
      a: "No. Smaller or fast-moving teams can go directly to subscription. Pilots are recommended for larger organizations that want proof of value before rollout.",
    },
    {
      q: "How is pricing calculated?",
      a: "Growth pricing is based on engineering seats. Enterprise pricing depends on team size, integration depth, governance needs, and reporting requirements.",
    },
    {
      q: "What does the pilot cover?",
      a: "The pilot is a limited deployment designed to prove value on real projects. It includes setup, risk monitoring, recommendations, simulation, support, and a final summary.",
    },
    {
      q: "Why is there custom enterprise pricing?",
      a: "Enterprise customers usually need broader rollout support, more integrations, and more governance controls than a standard plan includes.",
    },
    {
      q: "Can we start small and expand later?",
      a: "Yes. That is the recommended path for many teams.",
    },
  ];

  return (
    <div className="page pricing-page">
      <section ref={heroReveal.ref} className={`pricing-hero reveal-block ${heroReveal.isVisible ? "is-visible" : ""}`}>
        <div className="parallax-orb orb-c" />
        <p className="eyebrow">Pricing</p>
        <h1>Choose the rollout model that fits your team.</h1>
        <p className="pricing-intro">Start with a low-friction pilot or go straight to subscription.</p>
        <p className="pricing-intro">DevIQ helps engineering teams detect delivery risk early, recommend what to do next, and simulate disruption before deadlines slip.</p>
      </section>

      <section ref={gridReveal.ref} className={`pricing-plan-grid reveal-block ${gridReveal.isVisible ? "is-visible" : ""}`}>
        {plans.map((plan, index) => (
          <article key={plan.name} className={`pricing-card glass-card reveal-card ${gridReveal.isVisible ? "is-visible" : ""} ${plan.featured ? "featured-pricing" : ""}`} style={{ transitionDelay: `${index * 80}ms` }}>
            <div className="pricing-card-head">
              <div>
                <p className="eyebrow">{plan.name}</p>
                <h2>{plan.price}</h2>
              </div>
              <span className="pricing-cta-tag">{plan.cta}</span>
            </div>
            <p className="pricing-copy">{plan.subtitle}</p>
            <div className="pricing-block">
              <h3>Includes</h3>
              <SimpleList items={plan.includes} />
            </div>
            <div className="pricing-block">
              <h3>Best for</h3>
              <SimpleList items={plan.bestFor} />
            </div>
            {plan.breakdown.length ? (
              <div className="pricing-block">
                <h3>Pricing breakdown</h3>
                <SimpleList items={plan.breakdown} />
              </div>
            ) : null}
            <a className={`button ${plan.featured ? "primary" : "secondary"} pricing-button`} href="#/pricing">
              {plan.cta}
            </a>
          </article>
        ))}
      </section>

      <section className="pricing-support-grid">
        <PanelCard title="What’s Included In Every Plan" subtitle="Shared product value across pilot, growth, and enterprise">
          <SimpleList items={includedInEveryPlan} />
        </PanelCard>
        <PanelCard title="Frequently Asked Questions" subtitle="Quick answers for rollout and pricing decisions">
          <div className="faq-list">
            {faqs.map((item) => (
              <article key={item.q} className="faq-item">
                <strong>{item.q}</strong>
                <p>{item.a}</p>
              </article>
            ))}
          </div>
        </PanelCard>
      </section>

      <section className="pricing-final-cta glass-card">
        <p className="eyebrow">Final CTA</p>
        <h2>Prevent delivery surprises before they happen.</h2>
        <p>Start with a pilot or talk to us about a full rollout.</p>
        <div className="cta-row">
          <a className="button primary" href="#/pricing">Start Pilot</a>
          <a className="button secondary" href="#/pricing">Contact Sales</a>
        </div>
      </section>
    </div>
  );
}

function RiskPage() {
  const heroReveal = useRevealOnView();
  const gridReveal = useRevealOnView();
  const [riskRows, setRiskRows] = useState([]);
  const [selectedRisk, setSelectedRisk] = useState(null);
  const [issueInput, setIssueInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function loadRiskRows() {
      setLoading(true);
      setError("");
      try {
        const response = await fetch(`${RISK_API_BASE_URL}/api/risk/requirements?limit=12`);
        if (!response.ok) throw new Error(`Risk engine request failed with ${response.status}`);
        const payload = await response.json();
        if (!active) return;
        const requirements = Array.isArray(payload.requirements) ? payload.requirements : [];
        setRiskRows(requirements);
        setSelectedRisk(requirements[0] ?? null);
      } catch (fetchError) {
        if (!active) return;
        setError(fetchError.message || "Failed to load risk data");
      } finally {
        if (active) setLoading(false);
      }
    }
    loadRiskRows();
    return () => {
      active = false;
    };
  }, []);

  async function fetchSingleRequirementRisk(issueId) {
    const normalized = issueId.trim().toUpperCase();
    if (!normalized) return;

    setLookupLoading(true);
    setError("");
    try {
      const response = await fetch(`${RISK_API_BASE_URL}/api/risk/requirement/${encodeURIComponent(normalized)}`);
      if (!response.ok) throw new Error(`Risk engine request failed with ${response.status}`);
      const payload = await response.json();
      setSelectedRisk(payload);
      setRiskRows((current) => {
        const existing = current.filter((item) => item.requirement_id !== payload.requirement_id);
        return [payload, ...existing];
      });
      setIssueInput(normalized);
    } catch (fetchError) {
      setError(fetchError.message || "Failed to load selected requirement risk");
    } finally {
      setLookupLoading(false);
    }
  }

  const highRiskCount = riskRows.filter((item) => item.risk_level === "HIGH").length;
  const mediumRiskCount = riskRows.filter((item) => item.risk_level === "MEDIUM").length;
  const avgRisk = riskRows.length
    ? Math.round((riskRows.reduce((sum, item) => sum + Number(item.risk_score || 0), 0) / riskRows.length) * 100)
    : 0;

  const riskTableRows = riskRows.map((item) => ({
    issue_id: item.requirement_id,
    title: item.title || "Untitled requirement",
    risk_score: `${Math.round(Number(item.risk_score || 0) * 100)}%`,
    risk_level: item.risk_level || "Unknown",
    due_date: item.due_date ? formatDate(item.due_date) : "No due date",
    recommendation: Array.isArray(item.recommendations) && item.recommendations.length ? item.recommendations[0] : "No recommendation",
  }));

  const selectedBreakdown = selectedRisk
    ? [
        { label: "Activity Drop", value: Math.round(Number(selectedRisk.breakdown?.activity_drop || 0) * 100), tone: "amber" },
        { label: "Schedule Gap", value: Math.round(Number(selectedRisk.breakdown?.schedule_gap || 0) * 100), tone: "purple" },
        { label: "Developer Load", value: Math.round(Number(selectedRisk.breakdown?.developer_load || 0) * 100), tone: "cyan" },
        { label: "Complexity", value: Math.round(Number(selectedRisk.breakdown?.complexity || 0) * 100), tone: "green" },
        { label: "Staleness", value: Math.round(Number(selectedRisk.breakdown?.staleness || 0) * 100), tone: "amber" },
      ]
    : [];

  return (
    <div className="page dashboard-page risk-page">
      <section ref={heroReveal.ref} className={`dashboard-hero dashboard-stage reveal-block ${heroReveal.isVisible ? "is-visible" : ""}`}>
        <div className="parallax-orb orb-c" />
        <div>
          <p className="eyebrow">Requirement Risk</p>
          <h1>Track delivery risk requirement by requirement with clear explanations.</h1>
          <p className="hero-text narrow">
            This page turns live requirement activity into a clean risk review for managers: what is at risk, why it is at risk, and what the team should do next.
          </p>
          <div className="risk-lookup-card">
            <p className="eyebrow" style={{ margin: 0 }}>Requirement Lookup</p>
            <div className="risk-lookup-row">
              <input
                className="risk-lookup-input"
                placeholder="Enter issue ID, for example KAN-19"
                value={issueInput}
                onChange={(event) => setIssueInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") fetchSingleRequirementRisk(issueInput);
                }}
              />
              <button
                type="button"
                className="button primary"
                onClick={() => fetchSingleRequirementRisk(issueInput)}
                disabled={lookupLoading}
              >
                {lookupLoading ? "Loading..." : "Load Requirement"}
              </button>
            </div>
          </div>
        </div>
        <div className="glass-card dashboard-float reveal-card is-visible" style={{ padding: "22px", display: "grid", gap: "14px" }}>
          <p className="eyebrow" style={{ margin: 0 }}>Live portfolio view</p>
          <div className="prediction-summary">
            <article className="prediction-summary-card">
              <strong>{loading ? "..." : `${avgRisk}%`}</strong>
              <p>Average risk across tracked requirements</p>
            </article>
            <article className="prediction-summary-card">
              <strong>{loading ? "..." : highRiskCount}</strong>
              <p>Requirements currently in high-risk state</p>
            </article>
            <article className="prediction-summary-card">
              <strong>{loading ? "..." : mediumRiskCount}</strong>
              <p>Requirements that need attention soon</p>
            </article>
          </div>
        </div>
      </section>

      {error ? (
        <StateCard
          title="Risk engine not reachable"
          text={`${error}. Make sure the Risk Engine is running at ${RISK_API_BASE_URL}.`}
          error
          className="reveal-card is-visible"
        />
      ) : null}

      <section ref={gridReveal.ref} className={`dashboard-grid intelligence-grid reveal-block ${gridReveal.isVisible ? "is-visible" : ""}`}>
        <PanelCard title="Requirement Risk Register" subtitle="All tracked requirements ranked by current risk" className={`span-2 reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          {loading ? (
            <p className="empty-state">Loading requirement risk signals...</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th>Title</th>
                    <th>Risk</th>
                    <th>Level</th>
                    <th>Due Date</th>
                    <th>Next Step</th>
                  </tr>
                </thead>
                <tbody>
                  {riskRows.length ? riskRows.map((item) => (
                    <tr
                      key={item.requirement_id}
                      className={selectedRisk?.requirement_id === item.requirement_id ? "risk-table-row active" : "risk-table-row"}
                      onClick={() => setSelectedRisk(item)}
                    >
                      <td>{item.requirement_id}</td>
                      <td>{item.title || "Untitled requirement"}</td>
                      <td>{Math.round(Number(item.risk_score || 0) * 100)}%</td>
                      <td>{item.risk_level || "Unknown"}</td>
                      <td>{item.due_date ? formatDate(item.due_date) : "No due date"}</td>
                      <td>{Array.isArray(item.recommendations) && item.recommendations.length ? item.recommendations[0] : "No recommendation"}</td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan="6">No live risk rows available yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </PanelCard>

        <PanelCard title="Selected Requirement" subtitle={selectedRisk ? `${selectedRisk.requirement_id} risk detail` : "Choose a requirement to inspect"} className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          {selectedRisk ? (
            <div className="risk-detail-stack">
              <div className="prediction-metric amber">
                <span>Risk Score</span>
                <strong>{Math.round(Number(selectedRisk.risk_score || 0) * 100)}%</strong>
                <p>{selectedRisk.risk_level} risk based on live requirement activity and time progression.</p>
              </div>
              <div className="prediction-summary-card">
                <strong>Deadline</strong>
                <p>{selectedRisk.due_date ? formatDate(selectedRisk.due_date) : "No due date in Jira yet."}</p>
              </div>
              <div className="prediction-summary-card">
                <strong>Days Remaining</strong>
                <p>{selectedRisk.days_remaining ?? "N/A"}</p>
              </div>
            </div>
          ) : (
            <p className="empty-state">Select a requirement from the table to see detailed risk information.</p>
          )}
        </PanelCard>

        <PanelCard title="Risk Breakdown" subtitle="Which signals are pushing the score upward" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          {selectedRisk ? <ContributionBreakdown items={selectedBreakdown} /> : <p className="empty-state">No breakdown available.</p>}
        </PanelCard>

        <PanelCard title="Why This Requirement Is At Risk" subtitle="Top explanation factors from the backend engine" className={`reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          {selectedRisk ? <SimpleList items={selectedRisk.reasons || []} /> : <p className="empty-state">No reasons available.</p>}
        </PanelCard>

        <PanelCard title="Recommended Actions" subtitle="What the team should do next" className={`span-2 reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          {selectedRisk ? (
            <ActionCardList
              items={(selectedRisk.recommendations || []).map((item, index) => ({
                title: `Action ${index + 1}`,
                description: item,
                impact: "Expected to reduce delivery risk and improve schedule confidence.",
                priority: index === 0 ? "High" : index === 1 ? "Medium" : "Low",
              }))}
            />
          ) : (
            <p className="empty-state">No recommendations available.</p>
          )}
        </PanelCard>

        <PanelCard title="Portfolio Snapshot" subtitle="Quick scan of all current requirement risks" className={`span-2 reveal-card parallax-card ${gridReveal.isVisible ? "is-visible" : ""}`}>
          <DataTable
            columns={[
              { key: "issue_id", label: "Issue" },
              { key: "risk_score", label: "Risk Score" },
              { key: "risk_level", label: "Level" },
              { key: "due_date", label: "Due Date" },
              { key: "recommendation", label: "Primary Action" },
            ]}
            rows={riskTableRows}
            emptyMessage={loading ? "Loading risk snapshot..." : "No risk snapshot available yet."}
          />
        </PanelCard>
      </section>
    </div>
  );
}

function EstimationPage() {
  const heroReveal = useRevealOnView();
  const gridReveal = useRevealOnView();

  const [issueId, setIssueId] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [estimate, setEstimate] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [allEstimates, setAllEstimates] = useState([]);
  const [allLoading, setAllLoading] = useState(false);
  const [allError, setAllError] = useState("");
  const [showAll, setShowAll] = useState(false);

  async function fetchAllEstimates() {
    setAllLoading(true);
    setAllError("");
    setShowAll(true);
    try {
      // Fetch all requirements from Supabase via the deployed req_codemapping API
      const res = await fetch(`${API_BASE_URL}/api/dashboard`);
      if (!res.ok) throw new Error(`Dashboard fetch failed with status ${res.status}`);
      const data = await res.json();
      const issues = data.issues ?? [];
      if (!issues.length) { setAllEstimates([]); return; }

      // Run estimates for each issue in parallel (cap at 20 to avoid overload)
      const batch = issues.slice(0, 20);
      const results = await Promise.all(
        batch.map(async (issue) => {
          try {
            const estRes = await fetch(`${ESTIMATE_API_BASE_URL}/estimate/from-issue/${encodeURIComponent(issue.issue_id)}`);
            if (!estRes.ok) return { issue_id: issue.issue_id, title: issue.title, status: issue.status, priority: issue.priority, final_score: null, heuristic_score: null, llm_score: null, confidence: null, uncertainty: null, error: `HTTP ${estRes.status}` };
            const est = await estRes.json();
            return { issue_id: issue.issue_id, title: est.title || issue.title, status: issue.status, priority: issue.priority, final_score: est.final_score, heuristic_score: est.heuristic_score, llm_score: est.llm_score, confidence: est.confidence, uncertainty: est.uncertainty, error: null };
          } catch (e) {
            return { issue_id: issue.issue_id, title: issue.title, status: issue.status, priority: issue.priority, final_score: null, heuristic_score: null, llm_score: null, confidence: null, uncertainty: null, error: e.message };
          }
        })
      );
      setAllEstimates(results);
    } catch (err) {
      setAllError(err.message || "Failed to load all estimates");
    } finally {
      setAllLoading(false);
    }
  }

  async function fetchEstimate(id) {
    if (!id.trim()) return;
    setLoading(true);
    setError("");
    setEstimate(null);
    setHistory([]);
    setShowAll(false);
    try {
      const [estRes, histRes] = await Promise.all([
        fetch(`${ESTIMATE_API_BASE_URL}/estimate/from-issue/${encodeURIComponent(id.trim())}`),
        fetch(`${ESTIMATE_API_BASE_URL}/estimate/history/${encodeURIComponent(id.trim())}`),
      ]);
      if (!estRes.ok) throw new Error(`Estimate request failed with status ${estRes.status}`);
      const estData = await estRes.json();
      setEstimate(estData);
      if (histRes.ok) {
        const histData = await histRes.json();
        setHistory(Array.isArray(histData) ? histData : []);
      }
    } catch (err) {
      setError(err.message || "Failed to fetch estimate");
    } finally {
      setLoading(false);
    }
  }

  const driftTone = estimate
    ? estimate.final_score > 20 ? "amber" : estimate.final_score > 10 ? "purple" : "green"
    : "cyan";

  const breakdownItems = estimate?.estimate_breakdown ?? [];
  const totalBreakdownHours = breakdownItems.reduce((sum, t) => sum + t.hours, 0);

  const historyTrend = history.slice(0, 5).reverse().map((entry, i) => ({
    label: `#${i + 1}`,
    value: Math.round(entry.updated_score),
  }));

  return (
    <div className="page dashboard-page">
      <section
        ref={heroReveal.ref}
        className={`dashboard-hero dashboard-stage reveal-block ${heroReveal.isVisible ? "is-visible" : ""}`}
      >
        <div className="parallax-orb orb-c" />
        <div>
          <p className="eyebrow">Effort Estimation</p>
          <h1>Predict effort before work begins.</h1>
          <p className="hero-text narrow">
            Enter a Jira issue ID to generate a hybrid heuristic and LLM-backed effort estimate,
            see drift signals, and track how the score has evolved over time.
          </p>
        </div>
        <div className="glass-card dashboard-float reveal-card is-visible" style={{ padding: "22px", display: "grid", gap: "14px" }}>
          <p className="eyebrow" style={{ margin: 0 }}>Look up an issue</p>
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <input
              style={{
                flex: "1 1 180px",
                padding: "12px 16px",
                borderRadius: "14px",
                border: "1px solid rgba(17,17,17,0.12)",
                background: "rgba(255,255,255,0.96)",
                color: "#111",
                outline: "none",
                font: "inherit",
              }}
              placeholder="e.g. DEV-42"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { setIssueId(inputValue); fetchEstimate(inputValue); } }}
            />
            <button
              className="button primary"
              onClick={() => { setIssueId(inputValue); fetchEstimate(inputValue); }}
              disabled={loading}
            >
              {loading ? "Loading…" : "Estimate"}
            </button>
          </div>
          {issueId && !loading && !error && (
            <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.85rem" }}>
              Showing results for <strong>{issueId}</strong>
            </p>
          )}
        </div>
      </section>

      {error ? (
        <StateCard
          title="Estimation service not reachable"
          text={`${error}. Make sure the Estimate Engine is running at ${ESTIMATE_API_BASE_URL}.`}
          error
          className="reveal-card is-visible"
        />
      ) : null}

      {estimate ? (
        <>
          <section className="kpi-grid reveal-card is-visible" style={{ marginBottom: "18px" }}>
            <div className="kpi-card cyan">
              <div className="kpi-topline"><span>Final Estimate</span></div>
              <strong>{estimate.final_score} hrs</strong>
              <p>Blended heuristic and LLM score</p>
            </div>
            <div className="kpi-card purple">
              <div className="kpi-topline"><span>Heuristic Score</span></div>
              <strong>{estimate.heuristic_score} hrs</strong>
              <p>Keyword and complexity analysis</p>
            </div>
            <div className="kpi-card green">
              <div className="kpi-topline"><span>LLM Score</span></div>
              <strong>{estimate.llm_score} hrs</strong>
              <p>Ollama model estimate</p>
            </div>
            <div className={`kpi-card ${driftTone}`}>
              <div className="kpi-topline"><span>Confidence</span></div>
              <strong>{Math.round((estimate.confidence ?? 0) * 100)}%</strong>
              <p>Uncertainty: {estimate.uncertainty}</p>
            </div>
          </section>

          <section
            ref={gridReveal.ref}
            className={`dashboard-grid reveal-block ${gridReveal.isVisible ? "is-visible" : ""}`}
          >
            <PanelCard
              title="Requirement"
              subtitle={`Issue ${estimate.issue_id} — ${estimate.title || "No title"}`}
              className="span-2 reveal-card is-visible"
            >
              <p style={{ margin: 0, color: "var(--text-soft)", lineHeight: 1.65 }}>
                {estimate.requirement || "No requirement text available."}
              </p>
            </PanelCard>

            <PanelCard
              title="Task Breakdown"
              subtitle="Estimated hours per task from heuristic and LLM"
              className="reveal-card is-visible"
            >
              <div style={{ display: "grid", gap: "12px" }}>
                {breakdownItems.length ? breakdownItems.map((task, i) => (
                  <div key={i} style={{ display: "grid", gap: "6px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "10px" }}>
                      <span style={{ color: "#111", fontSize: "0.92rem" }}>{task.task}</span>
                      <strong style={{ whiteSpace: "nowrap" }}>{task.hours} hrs</strong>
                    </div>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{ width: `${totalBreakdownHours > 0 ? (task.hours / totalBreakdownHours) * 100 : 0}%` }}
                      />
                    </div>
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                      {task.source}
                    </span>
                  </div>
                )) : <p className="empty-state">No breakdown available.</p>}
              </div>
            </PanelCard>

            <PanelCard
              title="Score Comparison"
              subtitle="Heuristic vs LLM vs Final"
              className="reveal-card is-visible"
            >
              <div style={{ display: "grid", gap: "14px" }}>
                {[
                  { label: "Heuristic", value: estimate.heuristic_score, max: Math.max(estimate.heuristic_score, estimate.llm_score, estimate.final_score, 1) },
                  { label: "LLM", value: estimate.llm_score, max: Math.max(estimate.heuristic_score, estimate.llm_score, estimate.final_score, 1) },
                  { label: "Final", value: estimate.final_score, max: Math.max(estimate.heuristic_score, estimate.llm_score, estimate.final_score, 1) },
                ].map((item) => (
                  <div key={item.label} style={{ display: "grid", gap: "6px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "var(--text-soft)" }}>{item.label}</span>
                      <strong>{item.value} hrs</strong>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${(item.value / item.max) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </PanelCard>

            {historyTrend.length > 0 ? (
              <PanelCard
                title="Estimate History Trend"
                subtitle="How the score has changed over time"
                className="reveal-card is-visible"
              >
                <LineTrend items={historyTrend} />
              </PanelCard>
            ) : null}

            {history.length > 0 ? (
              <PanelCard
                title="Change History"
                subtitle="Every time this estimate was updated"
                className="span-2 reveal-card is-visible"
              >
                <DataTable
                  columns={[
                    { key: "changed_at_fmt", label: "When" },
                    { key: "previous_score", label: "Before (hrs)" },
                    { key: "updated_score", label: "After (hrs)" },
                    { key: "delta_score", label: "Delta" },
                    { key: "drift_level", label: "Drift" },
                    { key: "signal_type", label: "Signal" },
                    { key: "change_reason", label: "Reason" },
                  ]}
                  rows={history.map((entry) => ({
                    ...entry,
                    changed_at_fmt: entry.changed_at
                      ? new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(entry.changed_at))
                      : "N/A",
                    delta_score: entry.delta_score > 0 ? `+${entry.delta_score}` : String(entry.delta_score),
                  }))}
                  emptyMessage="No history entries found."
                />
              </PanelCard>
            ) : null}

            {estimate.breakdown?.heuristic_features?.length > 0 ? (
              <PanelCard
                title="Detected Features"
                subtitle="Keywords that influenced the heuristic score"
                className="reveal-card is-visible"
              >
                <div style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
                  {estimate.breakdown.heuristic_features.map((feature) => (
                    <span
                      key={feature}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        minHeight: "34px",
                        padding: "0 14px",
                        borderRadius: "999px",
                        border: "1px solid rgba(17,17,17,0.1)",
                        background: "rgba(17,17,17,0.05)",
                        color: "#111",
                        fontWeight: 600,
                        fontSize: "0.88rem",
                      }}
                    >
                      {feature}
                    </span>
                  ))}
                </div>
              </PanelCard>
            ) : null}

            {estimate.breakdown?.llm_summary ? (
              <PanelCard
                title="LLM Summary"
                subtitle="What the model said about this requirement"
                className="reveal-card is-visible"
              >
                <p style={{ margin: 0, color: "var(--text-soft)", lineHeight: 1.65 }}>
                  {estimate.breakdown.llm_summary}
                </p>
              </PanelCard>
            ) : null}

            {estimate.breakdown?.heuristic_rationale ? (
              <PanelCard
                title="Heuristic Rationale"
                subtitle="How the rule-based score was calculated"
                className="reveal-card is-visible"
              >
                <p style={{ margin: 0, color: "var(--text-soft)", lineHeight: 1.65 }}>
                  {estimate.breakdown.heuristic_rationale}
                </p>
              </PanelCard>
            ) : null}
          </section>
        </>
      ) : null}

      {!loading && !error && !estimate && issueId ? (
        <StateCard
          title="No estimate found"
          text={`No requirement was found for issue ID "${issueId}". Make sure it has been synced from Jira.`}
          className="reveal-card is-visible"
        />
      ) : null}
    </div>
  );
}

function SectionHead({ eyebrow, title }) {
  return <div className="section-heading"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>;
}

function PanelCard({ title, subtitle, children, className = "", style }) {
  return <section className={`glass-card panel-card ${className}`.trim()} style={style}><div className="panel-head"><h3>{title}</h3><p>{subtitle}</p></div>{children}</section>;
}

function StateCard({ title, text, error = false, className = "" }) {
  return <section className={`glass-card state-card ${error ? "error" : ""} ${className}`.trim()}><h3>{title}</h3><p>{text}</p></section>;
}

function MetricMini({ label, value, tone }) {
  return <div className={`metric-mini ${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}

function PredictionMetric({ label, value, tone, help }) {
  return (
    <div className={`prediction-metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{help}</p>
    </div>
  );
}

function PredictionSummary({ items }) {
  return (
    <div className="prediction-summary">
      {items.map((item) => (
        <article key={item.title} className="prediction-summary-card">
          <strong>{item.title}</strong>
          <p>{item.text}</p>
        </article>
      ))}
    </div>
  );
}

function LineTrend({ items, compact = false }) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);
  return <div className={compact ? "trend-chart compact" : "trend-chart"}>{items.map((item) => <div key={item.label} className="trend-point"><div className="trend-track"><div className="trend-fill" style={{ height: `${(item.value / maxValue) * 100}%` }} /></div><span>{item.label}</span></div>)}</div>;
}

function Leaderboard({ items }) {
  return <div className="leaderboard">{items.map((item, index) => <article key={item.name} className="leader-row"><div className="leader-rank">{index + 1}</div><div className="leader-copy"><strong>{item.name}</strong><span>{item.note}</span></div><div className="leader-score"><strong>{item.score}</strong><span>{item.shift}</span></div></article>)}</div>;
}

function HeatBars({ items }) {
  return <div className="heat-grid">{items.map((item) => <div key={item.label} className="heat-row"><div><strong>{item.label}</strong><span>{item.value}% load</span></div><div className="heat-track"><div className={`heat-fill ${item.tone}`} style={{ width: `${item.value}%` }} /></div></div>)}</div>;
}

function ContributionBreakdown({ items }) {
  return <div className="contribution-grid">{items.map((item) => <div key={item.label} className="contribution-card"><div className="contribution-head"><strong>{item.label}</strong><span>{item.value}%</span></div><div className="contribution-track"><div className={`contribution-fill ${item.tone}`} style={{ width: `${item.value}%` }} /></div></div>)}</div>;
}

function Meter() {
  return <div className="meter"><div className="meter-ring"><div className="meter-inner green"><strong>71%</strong><span>Balanced</span></div></div><p>You are delivering consistently without severe overload. Keep an eye on late sprint spikes.</p></div>;
}

function RadarList({ items }) {
  return <div className="radar-list">{items.map((item) => <div key={item.label} className="radar-row"><span>{item.label}</span><div className="radar-track"><div className="radar-fill" style={{ width: `${item.value}%` }} /></div><strong>{item.value}</strong></div>)}</div>;
}

function Timeline({ items }) {
  return <div className="timeline">{items.map((item) => <article key={`${item.title}-${item.meta}`} className="timeline-item"><div className="timeline-dot" /><div className="timeline-copy"><strong>{item.title}</strong><span>{item.meta}</span></div><em>{item.score}</em></article>)}</div>;
}

function SimpleList({ items }) {
  return <div className="simple-list">{items.map((item) => <p key={item}>{item}</p>)}</div>;
}

function ActionCardList({ items }) {
  return (
    <div className="action-card-list">
      {items.map((item) => (
        <article key={item.title} className="action-card">
          <div className="action-card-top">
            <strong>{item.title}</strong>
            <span className={`priority-badge ${item.priority.toLowerCase()}`}>{item.priority}</span>
          </div>
          <p>{item.description}</p>
          <small>{item.impact}</small>
        </article>
      ))}
    </div>
  );
}

function SimulationCard({ scopeReduction, setScopeReduction, addedDevelopers, setAddedDevelopers, simulatedRisk, simulatedDelay, projectedDeliveryDays }) {
  return (
    <div className="simulation-card">
      <label className="slider-field">
        <span>Reduce scope</span>
        <strong>{scopeReduction}%</strong>
        <input type="range" min="0" max="40" value={scopeReduction} onChange={(event) => setScopeReduction(Number(event.target.value))} />
      </label>
      <label className="slider-field">
        <span>Add developers</span>
        <strong>{addedDevelopers}</strong>
        <input type="range" min="0" max="4" value={addedDevelopers} onChange={(event) => setAddedDevelopers(Number(event.target.value))} />
      </label>
      <div className="simulation-results">
        <div><span>Projected Risk</span><strong>{Math.round(simulatedRisk)}</strong></div>
        <div><span>Delay Probability</span><strong>{Math.round(simulatedDelay)}%</strong></div>
        <div><span>Delivery Estimate</span><strong>{projectedDeliveryDays} days</strong></div>
      </div>
    </div>
  );
}

function BarList({ items }) {
  const rows = items.length ? items : [{ label: "No data", value: 0 }];
  const maxValue = Math.max(...rows.map((item) => item.value), 1);
  return <div className="bar-list">{rows.map((item) => <div key={item.label} className="bar-row"><div className="bar-meta"><span>{item.label}</span><strong>{item.value}</strong></div><div className="bar-track"><div className="bar-fill" style={{ width: `${(item.value / maxValue) * 100}%` }} /></div></div>)}</div>;
}

function DataTable({ columns, rows, emptyMessage }) {
  if (!rows.length) return <p className="empty-state">{emptyMessage}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={row.id || row.issue_id || row.commit_id || index}>{columns.map((column) => <td key={column.key}>{row[column.key] ?? "N/A"}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function ExplainabilityModal({ card, onClose }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div className="modal-card" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head"><div><p className="eyebrow">Explainability</p><h3>{card.title}</h3></div><button type="button" className="close-button" onClick={onClose}>Close</button></div>
        <p>{card.reason}</p>
        <div className="explain-grid"><div><span>Current Signal</span><strong>{card.value}</strong></div><div><span>Trend</span><strong>{card.change}</strong></div></div>
      </div>
    </div>
  );
}

function HeroLoader({ progress }) {
  const percent = Math.round(clamp(progress, 0, 1) * 100);

  return (
    <div className="hero-loader" role="status" aria-live="polite">
      <div className="hero-loader-card">
        <p className="eyebrow">DevGraph AI</p>
        <h2>Loading cinematic hero</h2>
        <div className="hero-loader-bar">
          <span style={{ width: `${percent}%` }} />
        </div>
        <strong>{percent}%</strong>
      </div>
    </div>
  );
}

function getRoute() {
  const value = ((window.location.hash || "#/").replace(/^#/, "").replace(/\/+$/, "") || "/");
  if (value === "/pricing") return "pricing";
  if (value === "/risk") return "risk";
  if (value === "/intelligence") return "intelligence";
  if (value === "/manager") return "manager";
  if (value === "/developer") return "developer";
  if (value === "/estimation") return "estimation";
  return "landing";
}

function formatDate(value) {
  if (!value) return "N/A";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function groupCounts(rows, key) {
  const counts = rows.reduce((accumulator, row) => {
    const label = row[key] || "Unknown";
    accumulator[label] = (accumulator[label] || 0) + 1;
    return accumulator;
  }, {});
  return Object.entries(counts).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
}

function buildLeaderboard(events) {
  const grouped = groupCounts(events, "author");
  const base = grouped.length ? grouped.slice(0, 4) : [{ label: "Anu", value: 8 }, { label: "Riya", value: 6 }, { label: "Karthik", value: 5 }, { label: "Nikhil", value: 4 }];
  return base.map((item, index) => ({ name: item.label, score: clamp(70 - index * 6 + item.value * 2.5, 0, 99).toFixed(0), shift: index === 0 ? "+4" : index === 1 ? "+2" : index === 2 ? "0" : "-1", note: index < 2 ? "High architectural leverage" : "Steady execution with healthy collaboration" }));
}

function buildDailyTrend(events, issues) {
  const issueMap = new Map(
    issues.map((issue) => [String(issue.issue_id || "").trim(), issue]),
  );
  const grouped = new Map();

  events.forEach((event) => {
    if (!event.timestamp) return;
    const date = new Date(event.timestamp);
    if (Number.isNaN(date.getTime())) return;
    const key = date.toISOString().slice(0, 10);
    const entry = grouped.get(key) || {
      commits: 0,
      changes: 0,
      authors: new Set(),
      linkedIssues: new Set(),
      unlinkedCommits: 0,
    };

    entry.commits += 1;
    entry.changes += Number(event.total_changes || 0);
    if (event.author) entry.authors.add(String(event.author));

    const directIssueId = String(event.issue_id || "").trim();
    if (directIssueId && issueMap.has(directIssueId)) {
      entry.linkedIssues.add(directIssueId);
    } else {
      entry.unlinkedCommits += 1;
    }

    grouped.set(key, entry);
  });

  const rows = [...grouped.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .slice(-5)
    .map(([date, entry]) => {
      const contributorSpread = entry.authors.size;
      const linkageScore = entry.commits ? (entry.linkedIssues.size / entry.commits) * 100 : 0;
      const churnScore = clamp(entry.changes / 2.6, 0, 42);
      const volumeScore = clamp(entry.commits * 8, 0, 32);
      const concentrationPenalty = clamp(24 - contributorSpread * 6, 0, 24);
      const unlinkedPenalty = clamp(entry.unlinkedCommits * 10, 0, 30);
      const linkageRelief = clamp(linkageScore * 0.22, 0, 18);

      const value = Math.round(
        clamp(28 + volumeScore + churnScore + concentrationPenalty + unlinkedPenalty - linkageRelief, 8, 99),
      );

      return {
        label: new Date(date).toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
        value,
      };
    });

  return rows.length
    ? rows
    : [
        { label: "W1", value: 34 },
        { label: "W2", value: 46 },
        { label: "W3", value: 41 },
        { label: "W4", value: 55 },
        { label: "W5", value: 49 },
      ];
}

function buildRepositoryRisk(events, issues) {
  const repoCounts = groupCounts(events, "repository_name").slice(0, 5);
  const linkedIssues = issues.filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0).length;
  return repoCounts.length
    ? repoCounts.map((item, index) => ({ label: item.label, value: clamp(35 + item.value * 9 + index * 4 - linkedIssues, 16, 94), tone: index === 0 ? "amber" : index === 1 ? "purple" : index === 2 ? "cyan" : "green" }))
    : [{ label: "Core Platform", value: 68, tone: "amber" }, { label: "Analytics", value: 54, tone: "purple" }, { label: "Extension", value: 41, tone: "cyan" }];
}

function buildRiskFactors({ issues, events, linkedIssues, avgAttendance, contributorCount }) {
  const unlinkedIssueRate = issues.length ? ((issues.length - linkedIssues) / issues.length) * 100 : 32;
  const workloadPressure = clamp(events.length * 6, 12, 88);
  const ownershipConcentration = clamp(82 - contributorCount * 10, 16, 78);
  const attendanceRisk = clamp(70 - avgAttendance, 10, 64);
  return [
    { label: "Unlinked requirements", value: Math.round(unlinkedIssueRate), tone: "amber" },
    { label: "Workload concentration", value: Math.round(workloadPressure), tone: "purple" },
    { label: "Ownership clarity gap", value: Math.round(ownershipConcentration), tone: "cyan" },
    { label: "Execution consistency", value: Math.round(attendanceRisk), tone: "green" },
  ];
}

function buildPrescriptions({ issues, events, linkedIssues, baseRisk, repositoryRisk }) {
  const topRepo = repositoryRisk[0]?.label || "Core platform";
  return [
    {
      title: `Stabilize ${topRepo}`,
      priority: baseRisk > 65 ? "High" : "Medium",
      description: `Concentrate senior review coverage on ${topRepo} for the next delivery window to reduce volatility.`,
      impact: `Estimated impact: reduces risk by ${Math.round(clamp(baseRisk / 4, 8, 22))}%`,
    },
    {
      title: "Increase requirement traceability",
      priority: issues.length > linkedIssues ? "High" : "Medium",
      description: "Link open requirements to active commits and freeze unclear tickets before new work starts.",
      impact: `Estimated impact: improves delivery confidence by ${Math.round(clamp((issues.length - linkedIssues) * 4, 6, 18))}%`,
    },
    {
      title: "Redistribute execution load",
      priority: events.length > 8 ? "Medium" : "Low",
      description: "Pair on the most active module so contribution risk is not concentrated in one workflow.",
      impact: "Estimated impact: lowers bottleneck probability and improves ownership resilience.",
    },
  ];
}

function buildAlerts({ baseRisk, delayProbability, repositoryRisk, linkedIssues, issues, syncInfo }) {
  const alerts = [];
  if (baseRisk > 65) alerts.push(`Risk increased to ${Math.round(baseRisk)} and now needs active mitigation.`);
  if (delayProbability > 70) alerts.push(`Delivery delay probability is ${Math.round(delayProbability)}%, which is above the safe threshold.`);
  if (repositoryRisk[0]) alerts.push(`${repositoryRisk[0].label} is the highest-risk module in the current activity window.`);
  if (issues.length > linkedIssues) alerts.push(`${issues.length - linkedIssues} requirements still have no linked delivery evidence.`);
  if (syncInfo?.linked_commits) alerts.push(`${syncInfo.linked_commits} linked commits are currently feeding the intelligence model.`);
  return alerts.length ? alerts : ["Signals are stable right now. No critical alerts in the current dataset."];
}

function buildDecisionTimeline(events, issues) {
  const issueEvents = issues.slice(0, 2).map((issue, index) => ({
    title: `Requirement ${issue.issue_id || `R-${index + 1}`} refreshed`,
    meta: issue.status || "Status updated",
    score: `${Array.isArray(issue.commits) ? issue.commits.length : 0} links`,
  }));
  const deliveryEvents = events.slice(0, 3).map((event, index) => ({
    title: event.message || `Delivery signal ${index + 1}`,
    meta: formatDate(event.timestamp),
    score: `${Number(event.total_changes || 0)} changes`,
  }));
  const rows = [...deliveryEvents, ...issueEvents];
  return rows.length ? rows : [{ title: "No decision events yet", meta: "Waiting for activity", score: "0" }];
}

function buildForecastCards({ issues, events, linkedIssues, baseRisk, delayProbability, confidence }) {
  const unlinkedCount = Math.max(issues.length - linkedIssues, 0);
  const recentCommitRate = buildDailyCommitCountTrend(events).reduce((sum, item) => sum + item.value, 0);
  return [
    {
      title: "Delay Outlook",
      text: delayProbability > 70 ? `Current patterns suggest a strong chance of delivery slippage unless intervention happens this week.` : `Delivery risk is present but still recoverable with moderate coordination.`,
    },
    {
      title: "Traceability Forecast",
      text: unlinkedCount > 0 ? `${unlinkedCount} requirements still lack commit evidence, so prediction confidence depends on improving linkage.` : `Requirement traceability is healthy enough to support more reliable forecasting.`,
    },
    {
      title: "Execution Momentum",
      text: recentCommitRate > 12 ? `Commit activity is high, which can drive progress but also increases the risk of overload and churn.` : `Execution tempo is moderate, which gives the team room to stabilize and document work.`,
    },
    {
      title: "Model Confidence",
      text: `${Math.round(confidence)}% confidence based on the current volume of linked issues and delivery activity in the database.`,
    },
  ];
}

function buildTopRequirementSignals(issues, events) {
  const commitMap = new Map(events.map((event) => [String(event.commit_id || ""), event]));
  return issues
    .map((issue) => {
      const commitIds = Array.isArray(issue.commits) ? issue.commits : [];
      const totalLinkedChanges = commitIds.reduce((sum, commitId) => sum + Number(commitMap.get(String(commitId))?.total_changes || 0), 0);
      return {
        issue_id: issue.issue_id || "Unknown",
        status: issue.status || "Unknown",
        priority: issue.priority || "Unknown",
        commits: commitIds.length,
        _weight: commitIds.length * 10 + totalLinkedChanges + (/high|highest/i.test(issue.priority || "") ? 20 : 0),
      };
    })
    .sort((a, b) => b._weight - a._weight)
    .slice(0, 5)
    .map(({ _weight, ...row }) => row);
}

function buildRequirementPredictions(issues, events) {
  const commitMap = new Map(events.map((event) => [String(event.commit_id || ""), event]));
  return issues
    .map((issue) => {
      const commitIds = Array.isArray(issue.commits) ? issue.commits : [];
      const linkedChanges = commitIds.reduce((sum, commitId) => sum + Number(commitMap.get(String(commitId))?.total_changes || 0), 0);
      const riskScore = clamp(
        (issue.priority === "High" || issue.priority === "Highest" ? 34 : 18) +
        (!commitIds.length ? 28 : 0) +
        (issue.status && /done|closed/i.test(issue.status) ? -18 : 10) +
        (linkedChanges > 80 ? 18 : linkedChanges > 20 ? 10 : 4),
        10,
        95,
      );
      return {
        issue_id: issue.issue_id || "Unknown",
        risk: `${Math.round(riskScore)}%`,
        reason: !commitIds.length
          ? "No linked commit evidence yet"
          : linkedChanges > 80
            ? "High code churn on linked commits"
            : `Linked activity exists but status is still ${issue.status || "open"}`,
        next_step: !commitIds.length
          ? "Link active work to this requirement and clarify ownership"
          : riskScore > 60
            ? "Freeze scope and add focused review support"
            : "Keep tracking delivery evidence",
        _score: riskScore,
      };
    })
    .sort((a, b) => b._score - a._score)
    .slice(0, 5)
    .map(({ _score, ...row }) => row);
}

function buildDeveloperPredictions(events, issues) {
  const linkedIssueCount = issues.filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0).length;
  return groupCounts(events, "author")
    .slice(0, 5)
    .map((item, index) => {
      const riskScore = clamp(24 + item.value * 11 + index * 4 - linkedIssueCount, 10, 92);
      return {
        developer: item.label,
        commits: item.value,
        risk: `${Math.round(riskScore)}%`,
        forecast: riskScore > 65 ? "Likely to become a bottleneck without support" : riskScore > 45 ? "Watch load and review ownership spread" : "Load appears manageable",
      };
    });
}

function buildDeveloperImpactBreakdown(events, issues) {
  const linkedRequirements = issues.filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0).length;
  const totalChanges = events.reduce((sum, event) => sum + Number(event.total_changes || 0), 0);
  const activeDevelopers = new Set(events.map((event) => event.author).filter(Boolean)).size;
  return [
    { label: "Commit Volume", value: Math.round(clamp(30 + events.length * 6, 0, 100)), tone: "cyan" },
    { label: "Requirement Linkage", value: Math.round(clamp(issues.length ? (linkedRequirements / issues.length) * 100 : 35, 0, 100)), tone: "purple" },
    { label: "Collaboration Spread", value: Math.round(clamp(25 + activeDevelopers * 14 + totalChanges / 20, 0, 100)), tone: "green" },
  ];
}

function buildDailyCommitCountTrend(events) {
  const grouped = new Map();
  events.forEach((event) => {
    if (!event.timestamp) return;
    const date = new Date(event.timestamp);
    if (Number.isNaN(date.getTime())) return;
    const key = date.toISOString().slice(0, 10);
    grouped.set(key, (grouped.get(key) || 0) + 1);
  });
  const rows = [...grouped.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .slice(-5)
    .map(([date, value]) => ({ label: new Date(date).toLocaleDateString("en-IN", { month: "short", day: "numeric" }), value }));
  return rows.length ? rows : [{ label: "Mon", value: 2 }, { label: "Tue", value: 4 }, { label: "Wed", value: 3 }, { label: "Thu", value: 5 }, { label: "Fri", value: 4 }];
}

function buildDeveloperTimelineClean(events) {
  const rows = events.slice(0, 4).map((event, index) => ({
    title: event.message || `Commit activity ${index + 1}`,
    meta: `${event.author || "Unknown"} - ${formatDate(event.timestamp)}`,
    score: `${Number(event.total_changes || 0)} changes`,
  }));
  return rows.length ? rows : developerTimeline;
}

function buildDeveloperTimelineFromEvents(events) {
  const rows = events.slice(0, 4).map((event, index) => ({
    title: event.message || `Commit activity ${index + 1}`,
    meta: `${event.author || "Unknown"} · ${formatDate(event.timestamp)}`,
    score: `${Number(event.total_changes || 0)} changes`,
  }));
  return rows.length ? rows : developerTimeline;
}

function buildDeveloperRadar(events, issues) {
  const linkedRequirements = issues.filter((issue) => Array.isArray(issue.commits) && issue.commits.length > 0).length;
  const totalChanges = events.reduce((sum, event) => sum + Number(event.total_changes || 0), 0);
  const activeDevelopers = new Set(events.map((event) => event.author).filter(Boolean)).size;
  return [
    { label: "Delivery", value: clamp(45 + events.length * 4, 0, 100) },
    { label: "Requirement Linkage", value: clamp(issues.length ? (linkedRequirements / issues.length) * 100 : 35, 0, 100) },
    { label: "Collaboration", value: clamp(35 + activeDevelopers * 12, 0, 100) },
    { label: "Code Throughput", value: clamp(28 + totalChanges / 4, 0, 100) },
    { label: "Consistency", value: clamp(40 + buildDailyCommitCountTrend(events).length * 8, 0, 100) },
  ];
}

function buildGrowthRecommendations(events, issues, linkedRequirements) {
  const recommendations = [];
  if (issues.length > linkedRequirements) recommendations.push("Link more open requirements to active commits so your work shows clearer delivery evidence.");
  if (events.length > 6) recommendations.push("Document one recent high-change contribution with a short design note to convert execution into visible leadership.");
  if (new Set(events.map((event) => event.repository_name).filter(Boolean)).size < 2) recommendations.push("Expand contribution spread across one more module to improve ownership coverage.");
  if (!recommendations.length) recommendations.push("Keep the current pace steady and continue converting delivery activity into traceable requirement progress.");
  return recommendations;
}

function filterEventsByManagerView(events, selectedFilter) {
  if (selectedFilter === "All Modules") return events;

  if (selectedFilter === "Current Sprint") {
    const latestTimestamp = getLatestTimestamp(events);
    if (!latestTimestamp) return events.slice(0, 12);
    const cutoff = latestTimestamp - 14 * 24 * 60 * 60 * 1000;
    const recentEvents = events.filter((event) => {
      const timestamp = Date.parse(event.timestamp || "");
      return !Number.isNaN(timestamp) && timestamp >= cutoff;
    });
    return recentEvents.length ? recentEvents : events.slice(0, 12);
  }

  if (selectedFilter === "Platform Team") {
    const platformEvents = events.filter((event) =>
      matchesPlatformScope([
        event.repository_name,
        event.message,
        event.branch,
        event.issue_id,
      ]),
    );
    return platformEvents.length ? platformEvents : events.slice(0, Math.min(events.length, 10));
  }

  return events;
}

function filterIssuesByManagerView(issues, scopedEvents, selectedFilter) {
  if (selectedFilter === "All Modules") return issues;

  const linkedIssueIds = new Set(
    scopedEvents
      .map((event) => String(event.issue_id || "").trim())
      .filter(Boolean),
  );
  const linkedCommitIds = new Set(
    scopedEvents
      .map((event) => String(event.commit_id || "").trim())
      .filter(Boolean),
  );
  const activeStatuses = new Set(["to do", "todo", "in progress", "in review", "open", "selected for development", "reopened"]);

  const scopedIssues = issues.filter((issue) => {
    const issueId = String(issue.issue_id || "").trim();
    const issueCommits = Array.isArray(issue.commits) ? issue.commits.map((commit) => String(commit).trim()) : [];
    const hasLinkedEvent = linkedIssueIds.has(issueId) || issueCommits.some((commit) => linkedCommitIds.has(commit));

    if (selectedFilter === "Current Sprint") {
      return hasLinkedEvent || activeStatuses.has(String(issue.status || "").trim().toLowerCase());
    }

    if (selectedFilter === "Platform Team") {
      return (
        hasLinkedEvent ||
        matchesPlatformScope([
          issue.project_key,
          issue.title,
          issue.issue_id,
          issue.status,
        ])
      );
    }

    return true;
  });

  return scopedIssues.length ? scopedIssues : issues.slice(0, Math.min(issues.length, 8));
}

function buildManagerOverviewTrend(events, issues) {
  const trend = buildDailyTrend(events, issues);
  return trend.map((item) => ({
    label: item.label,
    value: Math.round(clamp(100 - item.value + 18, 12, 96)),
  }));
}

function filterRows(rows, query, keys) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return rows;
  return rows.filter((row) =>
    keys.some((key) => {
      const value = row[key];
      if (value === null || value === undefined) return false;
      if (Array.isArray(value)) {
        return value.some((item) => String(item).toLowerCase().includes(normalized));
      }
      return String(value).toLowerCase().includes(normalized);
    }),
  );
}

function buildSearchSuggestions(events, issues, query) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return [];

  const suggestions = [];
  const seen = new Set();

  const pushSuggestion = (type, value, label, meta, score = 0) => {
    const normalizedValue = String(value || "").trim();
    if (!normalizedValue) return;
    const key = `${type}:${normalizedValue.toLowerCase()}`;
    if (seen.has(key)) return;
    seen.add(key);
    suggestions.push({ type, value: normalizedValue, label, meta, score });
  };

  issues.forEach((issue) => {
    const issueId = String(issue.issue_id || "").trim();
    const title = String(issue.title || "").trim();
    const projectKey = String(issue.project_key || "").trim();
    const searchable = [issueId, title, projectKey, issue.status, issue.priority].filter(Boolean).join(" ").toLowerCase();
    if (!searchable.includes(normalized)) return;
    const score = issueId.toLowerCase().startsWith(normalized) ? 30 : title.toLowerCase().includes(normalized) ? 20 : 10;
    pushSuggestion("Issue", issueId || title, issueId || title, `${issue.status || "Unknown status"} • ${issue.priority || "No priority"}`, score);
  });

  events.forEach((event) => {
    const author = String(event.author || "").trim();
    const repository = String(event.repository_name || "").trim();
    const commitId = String(event.commit_id || "").trim();
    const branch = String(event.branch || "").trim();
    const message = String(event.message || "").trim();

    if ([author, event.author_email].filter(Boolean).join(" ").toLowerCase().includes(normalized)) {
      pushSuggestion("Developer", author, author || "Unknown developer", repository ? `Active in ${repository}` : "Commit activity found", author.toLowerCase().startsWith(normalized) ? 28 : 16);
    }
    if ([repository, branch, message].filter(Boolean).join(" ").toLowerCase().includes(normalized)) {
      pushSuggestion("Repository", repository, repository || "Unknown repository", branch ? `Branch ${branch}` : "Repository activity found", repository.toLowerCase().startsWith(normalized) ? 26 : 14);
    }
    if ([commitId, message].filter(Boolean).join(" ").toLowerCase().includes(normalized)) {
      pushSuggestion("Commit", commitId || message, commitId || message || "Commit activity", author ? `By ${author}` : "Commit match", commitId.toLowerCase().startsWith(normalized) ? 24 : 12);
    }
    if (branch && branch.toLowerCase().includes(normalized)) {
      pushSuggestion("Branch", branch, branch, repository ? `${repository} branch` : "Branch match", branch.toLowerCase().startsWith(normalized) ? 22 : 11);
    }
  });

  return suggestions
    .sort((a, b) => b.score - a.score || a.label.localeCompare(b.label))
    .slice(0, 6);
}

function buildDeveloperFocus(activeSearchSuggestion, events, issues) {
  if (!activeSearchSuggestion || activeSearchSuggestion.type !== "Developer") return null;

  const target = String(activeSearchSuggestion.value || "").trim().toLowerCase();
  if (!target) return null;

  const developerEvents = events.filter((event) => {
    const author = String(event.author || "").trim().toLowerCase();
    const authorEmail = String(event.author_email || "").trim().toLowerCase();
    return author === target || authorEmail === target || author.includes(target);
  });

  if (!developerEvents.length) return null;

  const issueIds = new Set(
    developerEvents
      .map((event) => String(event.issue_id || "").trim())
      .filter(Boolean),
  );
  const commitIds = new Set(
    developerEvents
      .map((event) => String(event.commit_id || "").trim())
      .filter(Boolean),
  );
  const linkedRequirementsAll = issues.filter((issue) => {
    const issueId = String(issue.issue_id || "").trim();
    const linkedCommits = Array.isArray(issue.commits) ? issue.commits.map((commit) => String(commit).trim()) : [];
    return issueIds.has(issueId) || linkedCommits.some((commit) => commitIds.has(commit));
  });
  const requirementRows = linkedRequirementsAll
    .slice(0, 6);

  const repositories = groupCounts(developerEvents, "repository_name").slice(0, 5);
  const trend = buildDailyCommitCountTrend(developerEvents);
  const totalChanges = developerEvents.reduce((sum, event) => sum + Number(event.total_changes || 0), 0);
  const linkedRequirements = linkedRequirementsAll.length;
  const impactScore = Math.round(clamp(48 + developerEvents.length * 5 + linkedRequirements * 7 + totalChanges / 18, 0, 99));
  const name = activeSearchSuggestion.label || developerEvents[0]?.author || "Selected developer";
  const summary = `${name} touched ${linkedRequirements} requirements and worked mostly in ${repositories[0]?.label || "the current repositories"} during this scoped view.`;

  return {
    name,
    totalCommits: developerEvents.length,
    totalChanges,
    linkedRequirements,
    impactScore,
    summary,
    trend,
    repositories,
    commitRows: developerEvents.slice(0, 6).map((event) => ({
      ...event,
      timestamp: formatDate(event.timestamp),
      total_changes: Number(event.total_changes || 0),
    })),
    requirementRows,
  };
}

function buildIssueFocus(activeSearchSuggestion, events, issues) {
  if (!activeSearchSuggestion || activeSearchSuggestion.type !== "Issue") return null;

  const target = String(activeSearchSuggestion.value || "").trim().toLowerCase();
  if (!target) return null;

  const issue = issues.find((item) => String(item.issue_id || "").trim().toLowerCase() === target);
  if (!issue) return null;

  const issueId = String(issue.issue_id || "").trim();
  const linkedCommitIds = new Set(
    (Array.isArray(issue.commits) ? issue.commits : [])
      .map((commit) => String(commit).trim())
      .filter(Boolean),
  );

  const relatedEvents = events.filter((event) => {
    const eventIssueId = String(event.issue_id || "").trim().toLowerCase();
    const commitId = String(event.commit_id || "").trim();
    return eventIssueId === target || linkedCommitIds.has(commitId);
  });

  if (!relatedEvents.length) {
    return {
      issueId,
      status: issue.status || "Unknown",
      priority: issue.priority || "Not set",
      totalChanges: 0,
      commitCount: 0,
      repositories: [],
      developerContribution: [],
      commitRows: [],
      summary: `${issueId} is present in the requirement dataset, but there are no linked commits in the current scope yet.`,
    };
  }

  const repositories = groupCounts(relatedEvents, "repository_name").slice(0, 5);
  const developerContribution = groupCounts(relatedEvents, "author").slice(0, 5);
  const totalChanges = relatedEvents.reduce((sum, event) => sum + Number(event.total_changes || 0), 0);
  const topContributor = developerContribution[0]?.label || "the team";
  const summary = `${issue.title || issueId} is currently driven mostly by ${topContributor}, with ${relatedEvents.length} linked commits and ${totalChanges} tracked code changes in this scope.`;

  return {
    issueId,
    status: issue.status || "Unknown",
    priority: issue.priority || "Not set",
    totalChanges,
    commitCount: relatedEvents.length,
    repositories,
    developerContribution,
    summary,
    commitRows: relatedEvents.slice(0, 6).map((event) => ({
      ...event,
      timestamp: formatDate(event.timestamp),
      total_changes: Number(event.total_changes || 0),
    })),
  };
}

function average(values) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function metricCard(title, value, change, description, tone, reason) {
  return { title, value, change, description, tone, reason };
}

function matchesPlatformScope(values) {
  const platformKeywords = ["platform", "backend", "api", "infra", "core", "auth", "gateway", "sync"];
  const haystack = values
    .filter(Boolean)
    .map((value) => String(value).toLowerCase())
    .join(" ");
  return platformKeywords.some((keyword) => haystack.includes(keyword));
}

function getLatestTimestamp(events) {
  return events.reduce((latest, event) => {
    const timestamp = Date.parse(event.timestamp || "");
    if (Number.isNaN(timestamp)) return latest;
    return Math.max(latest, timestamp);
  }, 0);
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function useCinematicHeroVideo({ videoRef }) {
  const [isReady, setIsReady] = useState(false);
  const [loadProgress, setLoadProgress] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);
  const introLoopStart = 7;

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(mediaQuery.matches);
    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || reducedMotion) {
      setIsReady(true);
      setLoadProgress(1);
      return undefined;
    }

    let mounted = true;
    let introCompleted = false;

    const onReady = () => {
      if (mounted) setLoadProgress(0.72);
    };

    const onCanPlay = () => {
      if (mounted) setLoadProgress(0.9);
    };

    const onCanPlayThrough = () => {
      if (mounted) setIsReady(true);
      if (mounted) setLoadProgress(1);
    };

    const restartLoopSegment = async () => {
      const loopStart = Math.min(introLoopStart, Math.max((video.duration || introLoopStart) - 0.2, 0));
      video.currentTime = loopStart;
      try {
        await video.play();
      } catch {
        // Ignore autoplay restrictions here; user interaction can resume playback.
      }
    };

    const onTimeUpdate = () => {
      if (introCompleted && video.duration && video.currentTime >= Math.max(video.duration - 0.08, introLoopStart)) {
        video.currentTime = Math.min(introLoopStart, Math.max(video.duration - 0.2, 0));
      }
    };

    const onEnded = () => {
      introCompleted = true;
      restartLoopSegment();
    };

    const onPlay = () => {
      if (video.currentTime < introLoopStart - 0.05) {
        introCompleted = false;
      }
    };

    video.addEventListener("loadeddata", onReady);
    video.addEventListener("canplay", onCanPlay);
    video.addEventListener("canplaythrough", onCanPlayThrough);
    video.addEventListener("play", onPlay);
    video.addEventListener("timeupdate", onTimeUpdate);
    video.addEventListener("ended", onEnded);

    if (video.readyState >= 2) {
      onReady();
    }

    return () => {
      mounted = false;
      video.removeEventListener("loadeddata", onReady);
      video.removeEventListener("canplay", onCanPlay);
      video.removeEventListener("canplaythrough", onCanPlayThrough);
      video.removeEventListener("play", onPlay);
      video.removeEventListener("timeupdate", onTimeUpdate);
      video.removeEventListener("ended", onEnded);
    };
  }, [reducedMotion, videoRef]);

  return { isReady, loadProgress, reducedMotion };
}

function useHeroScrollProgress(sectionRef) {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let rafId = 0;

    const update = () => {
      const section = sectionRef.current;
      if (!section) return;

      const rect = section.getBoundingClientRect();
      const viewport = window.innerHeight;
      const total = Math.max(section.offsetHeight - viewport, 1);
      const traveled = clamp(-rect.top, 0, total);
      setProgress(traveled / total);
    };

    const onScroll = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(update);
    };

    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [sectionRef]);

  return progress;
}

function useRevealOnView() {
  const ref = useRef(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || isVisible) return undefined;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.18, rootMargin: "0px 0px -8% 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [isVisible]);

  return { ref, isVisible };
}

export default App;
