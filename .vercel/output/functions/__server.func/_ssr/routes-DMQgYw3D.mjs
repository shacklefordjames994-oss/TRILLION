import { i as __toESM } from "../_runtime.mjs";
import { n as require_jsx_runtime, r as require_react } from "../_libs/react+tanstack__react-query.mjs";
import { n as ShieldAlert, r as Ban } from "../_libs/lucide-react.mjs";
//#region node_modules/.nitro/vite/services/ssr/assets/routes-DMQgYw3D.js
var import_react = /* @__PURE__ */ __toESM(require_react());
var import_jsx_runtime = require_jsx_runtime();
var HumanAuthorityRequired = class extends Error {};
var InvalidSafetyTransition = class extends Error {};
var HumanAuthorityKillSwitch = class {
	authorized;
	used = /* @__PURE__ */ new Set();
	events;
	current;
	constructor(authorizedHumans) {
		const humans = new Set(authorizedHumans.map((actor) => actor.trim()).filter((actor) => actor.length > 0));
		if (humans.size === 0) throw new Error("At least one authorized human is required.");
		this.authorized = humans;
		this.current = {
			latched: true,
			revision: 1,
			reason: "Startup inhibit",
			changedBy: "SYSTEM",
			authorizationId: "BOOT"
		};
		this.events = [{
			revision: 1,
			action: "INHIBIT",
			actorId: "SYSTEM",
			reason: "Startup inhibit",
			authorizationId: "BOOT"
		}];
	}
	get state() {
		return { ...this.current };
	}
	get auditEvents() {
		return this.events.map((event) => ({ ...event }));
	}
	engage(actorId, reason) {
		if (!actorId.trim() || !reason.trim()) throw new Error("Actor and reason are required.");
		const revision = this.current.revision + 1;
		this.current = {
			latched: true,
			revision,
			reason: reason.trim(),
			changedBy: actorId.trim(),
			authorizationId: "INHIBIT"
		};
		this.events.push({
			revision,
			action: "INHIBIT",
			actorId: actorId.trim(),
			reason: reason.trim(),
			authorizationId: "INHIBIT"
		});
		return this.state;
	}
	reset(actorId, authorizationId, reason) {
		if (!this.authorized.has(actorId)) throw new HumanAuthorityRequired("Actor is not an authorized human.");
		if (!authorizationId.trim() || !reason.trim()) throw new HumanAuthorityRequired("A unique authorization ID and a reason are required.");
		if (!this.current.latched) throw new InvalidSafetyTransition("Latch is already clear.");
		const authId = authorizationId.trim();
		if (this.used.has(authId)) throw new HumanAuthorityRequired("Authorization ID has already been used.");
		this.used.add(authId);
		const revision = this.current.revision + 1;
		this.current = {
			latched: false,
			revision,
			reason: reason.trim(),
			changedBy: actorId,
			authorizationId: authId
		};
		this.events.push({
			revision,
			action: "RESET",
			actorId,
			reason: reason.trim(),
			authorizationId: authId
		});
		return this.state;
	}
	permitsSimulation() {
		return !this.current.latched;
	}
	permitsPhysicalExecution() {
		return false;
	}
};
var CRITICAL = /* @__PURE__ */ new Set([
	"SIGNATURE_INVALID",
	"POLICY_ROLLBACK_REJECTED",
	"AUDIT_INTEGRITY_FAILURE",
	"UNAUTHORIZED_POLICY_CHANGE",
	"SAFETY_STATE_UNAVAILABLE",
	"UNAPPROVED_PHYSICAL_COMMAND",
	"TRUSTED_STATE_REPLAY"
]);
function severityOf(code) {
	if (CRITICAL.has(code)) return "CRITICAL";
	if (code.startsWith("UNAPPROVED") || code.startsWith("GUARD_")) return "HIGH";
	return "WARNING";
}
function canonicalEvidence(evidence) {
	return `{${Object.keys(evidence).sort().map((key) => `${JSON.stringify(key)}:${JSON.stringify(evidence[key])}`).join(",")}}`;
}
async function sha256Hex(value) {
	const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
	return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
var IncidentDesk = class {
	killSwitch = new HumanAuthorityKillSwitch(["human-001"]);
	reviewers = /* @__PURE__ */ new Set(["human-001"]);
	reviewIds = /* @__PURE__ */ new Set();
	quarantined = /* @__PURE__ */ new Set();
	incidents = [];
	ledger = [];
	sequence = 0;
	task = "No task is queued. A reset will not create one.";
	memories = [{
		id: "experience-123",
		label: "Grasp of the red container",
		status: "VALIDATED"
	}, {
		id: "experience-keep",
		label: "Shelf placement, same cell",
		status: "VALIDATED"
	}];
	failQuarantineWrite = false;
	snapshot() {
		const permitted = this.killSwitch.permitsSimulation();
		return {
			latch: this.killSwitch.state,
			audit: this.killSwitch.auditEvents,
			incidents: this.incidents.map((incident) => ({
				...incident,
				actions: [...incident.actions]
			})),
			memories: this.memories.map((row) => ({ ...row })),
			retrieved: permitted ? this.memories.filter((row) => row.status === "VALIDATED").map((row) => row.id) : [],
			ledger: this.ledger.map((row) => ({ ...row })),
			task: this.task,
			physical: false
		};
	}
	quarantine(recordId, _incidentId) {
		const row = this.memories.find((item) => item.id === recordId);
		if (this.failQuarantineWrite) {
			if (row) row.status = "UNUSABLE";
			this.quarantined.add(recordId);
			return false;
		}
		if (!row) return false;
		row.status = "QUARANTINED";
		this.quarantined.add(recordId);
		return true;
	}
	async report(input) {
		let robotId = input.robotId;
		let code = input.code;
		let description = input.description;
		let policyRevision = input.policyRevision;
		if (!robotId.trim()) robotId = "UNKNOWN";
		if (!code.trim()) code = "UNCLASSIFIED_FAILURE";
		if (!description.trim()) description = "No description supplied.";
		if (!Number.isInteger(policyRevision) || policyRevision < 0) policyRevision = 0;
		const severity = severityOf(code);
		this.sequence += 1;
		const incidentId = (await sha256Hex(`${Date.now()}:${this.sequence}:${robotId}:${code}`)).slice(0, 24);
		const actions = [];
		if (severity === "CRITICAL") try {
			this.killSwitch.engage(robotId, `Incident ${incidentId}: ${code}`);
			actions.push("INHIBIT_REQUESTED");
			this.task = "Task dropped. Inhibit does not resume when the latch is later cleared.";
		} catch {
			actions.push("INHIBIT_REQUEST_FAILED");
		}
		let evidence;
		if ("circular" in input.evidence) {
			const box = {};
			box.self = box;
			evidence = box;
		} else evidence = input.evidence;
		let evidenceDigest = "UNAVAILABLE";
		try {
			evidenceDigest = await sha256Hex(canonicalEvidence(evidence));
		} catch {
			actions.push("EVIDENCE_DIGEST_FAILED");
		}
		let status = "OPEN";
		if (input.memoryRecordId) {
			if (this.quarantine(input.memoryRecordId, incidentId)) actions.push("MEMORY_QUARANTINED");
			else {
				status = "QUARANTINE_FAILED";
				actions.push("QUARANTINE_FAILED");
			}
		}
		const incident = {
			incidentId,
			robotId,
			code,
			severity,
			description,
			evidenceDigest,
			policyRevision,
			status,
			actions
		};
		this.incidents = [incident, ...this.incidents];
		this.ledger.push({
			actorId: robotId,
			eventType: `INCIDENT_${severity}`,
			reason: `id=${incidentId}; code=${code}; evidence_digest=${evidenceDigest}`
		});
		return incident;
	}
	approveReview(incidentId, reviewerId, reviewId, disposition) {
		if (!this.reviewers.has(reviewerId)) throw new Error("Reviewer is not authorized.");
		if (!reviewId.trim() || !disposition.trim()) throw new Error("Review ID and disposition are required.");
		if (!this.incidents.some((incident) => incident.incidentId === incidentId)) throw new Error("Unknown incident.");
		if (this.reviewIds.has(reviewId.trim())) throw new Error("Review ID has already been used.");
		this.reviewIds.add(reviewId.trim());
		this.ledger.push({
			actorId: reviewerId,
			eventType: "INCIDENT_HUMAN_REVIEW",
			reason: `incident=${incidentId}; review_id=${reviewId.trim()}; disposition=${disposition.trim()}`
		});
	}
	submitStep() {
		if (!this.killSwitch.permitsSimulation()) {
			this.task = "Step refused. The swarm is inhibited.";
			return this.task;
		}
		this.task = "Simulation step accepted for evaluation only. No actuator command was issued.";
		return this.task;
	}
};
async function runDeskChecks() {
	const checks = [];
	function add(name, pass, detail) {
		checks.push({
			name,
			pass,
			detail
		});
	}
	const desk = new IncidentDesk();
	const critical = await desk.report({
		robotId: "robot-007",
		code: "SIGNATURE_INVALID",
		description: "Policy signature verification failed",
		evidence: { policy_id: "policy-demo" },
		policyRevision: 4
	});
	add("Critical event inhibits first", desk.killSwitch.state.latched && critical.actions.includes("INHIBIT_REQUESTED"), critical.actions.join(", "));
	const memory = new IncidentDesk();
	memory.killSwitch.reset("human-001", "approval-check", "Check setup");
	await memory.report({
		robotId: "robot-007",
		code: "UNAPPROVED_BEHAVIOR",
		description: "Unapproved simulation action",
		evidence: { action: "unknown_action" },
		policyRevision: 4,
		memoryRecordId: "experience-123"
	});
	const hidden = memory.snapshot();
	const grasp = hidden.memories.find((row) => row.id === "experience-123");
	add("Suspect memory leaves retrieval", grasp?.status === "QUARANTINED" && !hidden.retrieved.includes("experience-123") && hidden.retrieved.includes("experience-keep"), grasp?.status ?? "missing");
	let unknown = false;
	try {
		memory.approveReview("missing-incident", "human-001", "review-x", "reject");
	} catch {
		unknown = true;
	}
	add("Unknown incident cannot be reviewed", unknown, unknown ? "rejected" : "accepted");
	let agent = false;
	try {
		memory.approveReview(hidden.incidents[0].incidentId, "agent-001", "review-y", "reject");
	} catch {
		agent = true;
	}
	add("Agent cannot review", agent, agent ? "rejected" : "accepted");
	memory.approveReview(hidden.incidents[0].incidentId, "human-001", "review-keep", "investigated");
	const afterReview = memory.snapshot();
	add("Review does not release quarantine", afterReview.memories.find((row) => row.id === "experience-123")?.status === "QUARANTINED" && !afterReview.retrieved.includes("experience-123"), "memory status unchanged");
	const reviewDesk = new IncidentDesk();
	const opened = await reviewDesk.report({
		robotId: "robot-007",
		code: "SIGNATURE_INVALID",
		description: "Test",
		evidence: { policy_id: "policy-demo" },
		policyRevision: 1
	});
	reviewDesk.approveReview(opened.incidentId, "human-001", "review-001", "investigated");
	add("Review leaves the latch closed", reviewDesk.killSwitch.state.latched && reviewDesk.killSwitch.permitsPhysicalExecution() === false, `latched=${reviewDesk.killSwitch.state.latched}`);
	const messy = new IncidentDesk();
	const messyResult = await messy.report({
		robotId: "robot-007",
		code: "AUDIT_INTEGRITY_FAILURE",
		description: "Evidence could not be serialized",
		evidence: { circular: true },
		policyRevision: 3
	});
	add("Undigestible evidence still inhibits", messy.killSwitch.state.latched && messyResult.actions.includes("INHIBIT_REQUESTED") && messyResult.actions.includes("EVIDENCE_DIGEST_FAILED") && messyResult.evidenceDigest === "UNAVAILABLE", messyResult.actions.join(", "));
	return checks;
}
var EMPTY = {
	latch: {
		latched: true,
		revision: 1,
		reason: "Startup inhibit",
		changedBy: "SYSTEM",
		authorizationId: "BOOT"
	},
	audit: [],
	incidents: [],
	memories: [],
	retrieved: [],
	ledger: [],
	task: "No task is queued. A reset will not create one.",
	physical: false
};
function IncidentDeskView() {
	const deskRef = (0, import_react.useRef)(null);
	if (deskRef.current === null) deskRef.current = new IncidentDesk();
	const desk = deskRef.current;
	const [snap, setSnap] = (0, import_react.useState)(EMPTY);
	const [banner, setBanner] = (0, import_react.useState)(null);
	const [authId, setAuthId] = (0, import_react.useState)("");
	const [reviewId, setReviewId] = (0, import_react.useState)("");
	const [checks, setChecks] = (0, import_react.useState)([]);
	function refresh() {
		setSnap(desk.snapshot());
	}
	(0, import_react.useEffect)(() => {
		refresh();
		let cancel = false;
		runDeskChecks().then((rows) => {
			if (!cancel) setChecks(rows);
		});
		return () => {
			cancel = true;
		};
	}, []);
	async function run(action) {
		setBanner(null);
		try {
			await action();
		} catch (error) {
			setBanner(error instanceof Error ? error.message : "Action rejected.");
		}
		refresh();
	}
	const latched = snap.latch.latched;
	const latest = snap.incidents[0];
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("main", {
		className: "desk",
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("header", {
				className: "desk-top",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "eyebrow",
						children: "Optimus Ω · simulation policy"
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h1", { children: "Incident desk" }),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "lede",
						children: "A critical fault inhibits the swarm before evidence is read. Review records a decision. It does not clear the latch, restore a task, or move an actuator."
					})
				] }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "stamp",
					children: "Not a certified stop"
				})]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: latched ? "latch is-closed" : "latch is-open",
				"aria-live": "polite",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(ShieldAlert, { "aria-hidden": "true" }),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "latch-title",
						children: latched ? "Swarm inhibited" : "Simulation latch clear"
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", { children: [
						"Rev ",
						snap.latch.revision,
						" · ",
						snap.latch.changedBy,
						" · ",
						snap.latch.reason
					] })] }),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
						className: "physical",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Ban, { "aria-hidden": "true" }), " Physical execution disabled"]
					})
				]
			}),
			banner ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "banner",
				children: banner
			}) : null,
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "desk-grid",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "panel",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", { children: "Report" }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
							className: "actions",
							children: [
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
									type: "button",
									onClick: () => run(() => desk.report({
										robotId: "robot-007",
										code: "SIGNATURE_INVALID",
										description: "Policy signature verification failed",
										evidence: { policy_id: "policy-demo" },
										policyRevision: 4
									})),
									children: "Signature failure"
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
									type: "button",
									onClick: () => run(() => desk.report({
										robotId: "robot-007",
										code: "UNAPPROVED_BEHAVIOR",
										description: "Unapproved grasp offered as shared experience",
										evidence: { action: "unknown_action" },
										policyRevision: 4,
										memoryRecordId: "experience-123"
									})),
									children: "Quarantine grasp memory"
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
									type: "button",
									onClick: () => run(() => desk.report({
										robotId: "robot-007",
										code: "AUDIT_INTEGRITY_FAILURE",
										description: "Evidence could not be serialized",
										evidence: { circular: true },
										policyRevision: 3
									})),
									children: "Undigestible evidence"
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
									type: "button",
									className: "ghost",
									onClick: () => run(async () => {
										desk.failQuarantineWrite = true;
										try {
											await desk.report({
												robotId: "robot-007",
												code: "UNAPPROVED_BEHAVIOR",
												description: "Quarantine write failed",
												evidence: { action: "unknown_action" },
												policyRevision: 4,
												memoryRecordId: "experience-keep"
											});
										} finally {
											desk.failQuarantineWrite = false;
										}
									}),
									children: "Fail the quarantine write"
								})
							]
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "note",
							children: "Containment runs before the digest. If the evidence cannot be hashed, the inhibit still stands and the digest is marked unavailable."
						})
					]
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "panel",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", { children: "Human review" }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "note",
							children: latest ? `Open incident ${latest.incidentId}` : "Report an incident before review. An agent cannot approve one."
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", { children: ["Review id", /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
							value: reviewId,
							onChange: (event) => setReviewId(event.target.value),
							placeholder: "review-001",
							autoComplete: "off"
						})] }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
							className: "actions",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								className: "ghost",
								onClick: () => run(() => {
									if (!latest) throw new Error("Unknown incident.");
									desk.approveReview(latest.incidentId, "agent-001", reviewId || "review-agent", "reject");
								}),
								children: "Review as agent"
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								onClick: () => run(() => {
									if (!latest) throw new Error("Unknown incident.");
									desk.approveReview(latest.incidentId, "human-001", reviewId, "investigated — memory stays quarantined");
								}),
								children: "Review as human-001"
							})]
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", { children: ["Reset authorization", /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
							value: authId,
							onChange: (event) => setAuthId(event.target.value),
							placeholder: "approval-201",
							autoComplete: "off"
						})] }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
							className: "actions",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								onClick: () => run(() => desk.killSwitch.engage("robot-007", "Operator inhibit")),
								children: "Robot inhibit"
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								onClick: () => run(() => desk.killSwitch.reset("human-001", authId, "Reviewed the incident. This does not resume the task.")),
								children: "Human reset"
							})]
						})
					]
				})]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "panel",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "split-head",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", { children: "Shared memory" }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							type: "button",
							className: "ghost",
							onClick: () => run(() => desk.submitStep()),
							children: "Submit a new simulation step"
						})]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "task",
						children: snap.task
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
						className: "memory",
						children: snap.memories.map((row) => {
							const visible = snap.retrieved.includes(row.id);
							return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("strong", { children: row.id }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("small", { children: row.label })] }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("em", {
								className: visible ? "ok" : "held",
								children: visible ? "Retrieved" : row.status
							})] }, row.id);
						})
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "note",
						children: "Retrieval returns only VALIDATED rows, and only while the latch is clear. Review does not put a quarantined row back."
					})
				]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "desk-grid",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "panel",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", { children: "Incidents" }),
						snap.incidents.length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "note",
							children: "None yet. The swarm starts inhibited."
						}) : null,
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
							className: "cards",
							children: snap.incidents.map((incident) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
									className: "code",
									children: incident.code
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", { children: incident.description }),
								/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
									className: "meta",
									children: [
										incident.severity,
										" · ",
										incident.status,
										" · rev ",
										incident.policyRevision
									]
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
									className: "meta",
									children: ["Digest ", incident.evidenceDigest.slice(0, 16)]
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
									className: "meta",
									children: incident.actions.join(" · ")
								})
							] }, incident.incidentId))
						})
					]
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "panel",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", { children: "Authority log" }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("ul", {
						className: "log",
						children: [snap.audit.map((event) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: event.action }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", { children: [
							event.actorId,
							" · rev ",
							event.revision,
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("br", {}),
							event.reason
						] })] }, `${event.action}-${event.revision}`)), snap.ledger.map((row, index) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: row.eventType }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", { children: [
							row.actorId,
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("br", {}),
							row.reason
						] })] }, `${row.eventType}-${index}`))]
					})]
				})]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "panel checks",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", { children: "Local checks" }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("ul", { children: [checks.length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("li", { children: "Running the incident checks…" }) : null, checks.map((check) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", {
					className: check.pass ? "ok" : "held",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("strong", { children: check.pass ? "Pass" : "Fail" }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", { children: [check.name, /* @__PURE__ */ (0, import_jsx_runtime.jsx)("small", { children: check.detail })] })]
				}, check.name))] })]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("footer", {
				className: "limits",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", { children: "This desk is an in-browser model of the Python incident engine. It does not stop a physical robot, authenticate a person, or prove that a disconnected robot received the inhibit. Incident state here lives in the page. The research package keeps the same rule: human review is an audit entry, not a resume command." })
			})
		]
	});
}
var SplitComponent = IncidentDeskView;
//#endregion
export { SplitComponent as component };
