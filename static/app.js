// Custom JavaScript Engine - routerio Dashboard Controls

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const statRequests = document.getElementById("stat-requests");
    const statCache = document.getElementById("stat-cache");
    const statSavings = document.getElementById("stat-savings");
    const statLatency = document.getElementById("stat-latency");
    const logsCount = document.getElementById("logs-count");
    
    const providerBreakers = document.getElementById("provider-breakers");
    const logsTableBody = document.getElementById("logs-table-body");
    
    // Playground Elements
    const promptInput = document.getElementById("prompt-input");
    const policySelect = document.getElementById("policy-select");
    const complianceSelect = document.getElementById("compliance-select");
    const bypassCacheCheckbox = document.getElementById("bypass-cache-checkbox");
    const sendPromptBtn = document.getElementById("send-prompt-btn");
    const btnLoader = sendPromptBtn.querySelector(".btn-loader");
    
    const outputTraceContainer = document.getElementById("output-trace-container");
    const traceComplexity = document.getElementById("trace-complexity");
    const traceModel = document.getElementById("trace-model");
    const traceCacheStatus = document.getElementById("trace-cache-status");
    const traceStepsList = document.getElementById("trace-steps-list");
    const traceTextOutput = document.getElementById("trace-text-output");
    
    // Actions Elements
    const clearCacheBtn = document.getElementById("clear-cache-btn");
    const resetBreakersBtn = document.getElementById("reset-breakers-btn");

    // Chart.js Setup
    let providerChart = null;

    function initChart(data) {
        const ctx = document.getElementById('provider-chart').getContext('2d');
        
        const labels = Object.keys(data);
        const values = Object.values(data);
        
        // Default placeholders if no data
        const chartLabels = labels.length ? labels.map(l => l.toUpperCase()) : ["NO DATA"];
        const chartValues = values.length ? values : [1];
        const chartColors = labels.length ? 
            labels.map(l => {
                if (l === 'openai') return '#60a5fa';
                if (l === 'anthropic') return '#c084fc';
                if (l === 'google') return '#34d399';
                return '#fbbf24'; // ollama / local
            }) : ['rgba(255,255,255,0.05)'];

        if (providerChart) {
            providerChart.destroy();
        }

        providerChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: chartLabels,
                datasets: [{
                    data: chartValues,
                    backgroundColor: chartColors,
                    borderWidth: 1,
                    borderColor: 'rgba(255,255,255,0.08)'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            color: '#a1a1aa',
                            font: { family: 'Inter', size: 10 }
                        }
                    }
                }
            }
        });
    }

    // Refresh telemetry logs & analytics metrics
    async function updateDashboardData() {
        try {
            // 1. Fetch Analytics
            const resAnalytics = await fetch("/api/analytics");
            const analytics = await resAnalytics.json();
            
            statRequests.innerText = analytics.total_requests;
            statCache.innerText = `${analytics.cache_hit_rate}%`;
            statSavings.innerText = `$${analytics.total_saved.toFixed(2)}`;
            statLatency.innerText = `${analytics.average_latency_ms} ms`;
            
            initChart(analytics.provider_distribution || {});

            // 2. Fetch Circuit Breakers Status
            const resBreakers = await fetch("/api/circuit-breakers");
            const breakers = await resBreakers.json();
            providerBreakers.innerHTML = "";
            
            Object.keys(breakers).forEach(prov => {
                const b = breakers[prov];
                const isActive = b.status === "CLOSED" || b.status === "HALF-OPEN";
                
                const pill = document.createElement("div");
                pill.className = "provider-pill";
                pill.innerHTML = `
                    <span class="status-indicator ${isActive ? 'active' : 'tripped'}"></span>
                    <span>${prov.toUpperCase()}: ${b.status}</span>
                `;
                providerBreakers.appendChild(pill);
            });

            // 3. Fetch Recent Audit Logs
            const resLogs = await fetch("/api/logs");
            const logs = await resLogs.json();
            
            logsCount.innerText = `${logs.length} recorded`;
            logsTableBody.innerHTML = "";
            
            if (logs.length === 0) {
                logsTableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #71717a; padding: 2rem;">No logs recorded yet. Run a prompt query above to trigger routes.</td></tr>`;
            } else {
                logs.forEach(log => {
                    const row = document.createElement("tr");
                    const date = new Date(log.timestamp);
                    const formattedTime = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    
                    const cacheBadge = log.was_cached ? `<span class="badge-green">YES</span>` : `<span class="badge">NO</span>`;
                    const fallbackBadge = log.was_fallback ? `<span class="badge-red">YES</span>` : `<span class="badge">NO</span>`;
                    
                    row.innerHTML = `
                        <td style="font-family: monospace; color: #a1a1aa">${formattedTime}</td>
                        <td style="text-transform: capitalize; font-weight: 500">${log.policy}</td>
                        <td style="color: #e4e4e7" title="${log.prompt}">${log.prompt.length > 45 ? log.prompt.substring(0, 45) + '...' : log.prompt}</td>
                        <td style="font-family: monospace; color: #60a5fa">${log.actual_model}</td>
                        <td>${cacheBadge}</td>
                        <td>${fallbackBadge}</td>
                        <td style="font-weight: 600">${log.latency_ms} ms</td>
                        <td style="font-family: monospace; color: #34d399">$${log.cost.toFixed(5)}</td>
                    `;
                    logsTableBody.appendChild(row);
                });
            }

        } catch (err) {
            console.error("Failed pulling core metrics update:", err);
        }
    }

    // Trigger Playground routing post requests
    sendPromptBtn.addEventListener("click", async () => {
        const text = promptInput.value.trim();
        if (!text) {
            alert("Please type a testing prompt first.");
            return;
        }

        // Set Loading State
        sendPromptBtn.disabled = true;
        btnLoader.classList.remove("hidden");
        
        try {
            const payload = {
                messages: [{ role: "user", content: text }],
                policy: policySelect.value,
                compliance: complianceSelect.value,
                bypass_cache: bypassCacheCheckbox.checked
            };

            const res = await fetch("/v1/chat/completions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                throw new Error("Target routed gateway error response.");
            }

            const data = await res.json();
            
            // Render Decision Trace Logs
            outputTraceContainer.classList.remove("hidden");
            
            const meta = data.routerio_meta || {};
            const trace = meta.trace || {};
            
            traceComplexity.innerText = trace.complexity || "Cached (Instant)";
            traceModel.innerText = data.model;
            traceCacheStatus.innerText = meta.was_cached ? "Yes (Instant Hit)" : "No (Routed Upstream)";
            
            // Build step logs
            traceStepsList.innerHTML = "";
            if (meta.was_cached) {
                const li = document.createElement("li");
                li.innerText = `Semantic Cache matched with similarity of ${(meta.similarity * 100).toFixed(1)}%. Returning instant response.`;
                traceStepsList.appendChild(li);
            } else {
                // complexity steps
                if (trace.complexity_triggers) {
                    trace.complexity_triggers.forEach(trig => {
                        const li = document.createElement("li");
                        li.innerText = `Feature classification: ${trig}`;
                        traceStepsList.appendChild(li);
                    });
                }
                // path selection
                if (trace.routing_path) {
                    trace.routing_path.forEach(pathStep => {
                        const li = document.createElement("li");
                        li.innerText = pathStep;
                        traceStepsList.appendChild(li);
                    });
                }
            }

            traceTextOutput.innerText = data.choices[0].message.content;

            // Trigger updates to update counters
            await updateDashboardData();

        } catch (err) {
            alert("Error sending completion: Make sure the server is healthy.");
            console.error(err);
        } finally {
            sendPromptBtn.disabled = false;
            btnLoader.classList.add("hidden");
        }
    });

    // Dashboard global triggers
    clearCacheBtn.addEventListener("click", async () => {
        if (confirm("Clear cache data? All future queries must hit live / simulated upstream models.")) {
            await fetch("/api/cache/clear", { method: "POST" });
            updateDashboardData();
        }
    });

    resetBreakersBtn.addEventListener("click", async () => {
        await fetch("/api/circuit-breakers/reset", { method: "POST" });
        updateDashboardData();
    });

    // Start Polling Loops
    updateDashboardData();
    setInterval(updateDashboardData, 3000);
});
