(() => {
    "use strict";

    const payload = document.getElementById("benchmark-data");
    if (!payload) return;
    const data = JSON.parse(payload.textContent);
    const controls = {
        view: document.getElementById("report-view"),
        suite: document.getElementById("report-suite"),
        dataset: document.getElementById("report-dataset"),
        query: document.getElementById("report-query"),
        phase: document.getElementById("report-phase"),
    };
    const sections = [...document.querySelectorAll("section.workload")];
    const status = document.getElementById("report-status");
    const empty = document.getElementById("no-results");
    const scopeSummary = document.getElementById("scope-summary");
    const phaseLabels = {
        cold: "Cold process",
        warm: "Warm process",
        warmup: "Warm-up failure",
        legacy: "Legacy measurements",
    };
    const ratioFormat = new Intl.NumberFormat(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });

    function scopesFor(view) {
        if (view === "latest") {
            return data.scopes.filter((scope) => scope.id === data.latest_scope);
        }
        if (view === "history") {
            return data.scopes.filter((scope) =>
                scope.kind === "unassigned" ||
                (scope.kind === "suite" && scope.id !== data.latest_scope)
            );
        }
        return data.scopes.filter((scope) => scope.kind === "legacy");
    }

    function resetFilters() {
        controls.dataset.value = "";
        controls.query.value = "";
        controls.phase.value = "";
    }

    function selectScope() {
        const scopes = scopesFor(controls.view.value);
        controls.suite.replaceChildren(...scopes.map((scope) =>
            new Option(scope.label, scope.id)
        ));
        if (!scopes.length) {
            controls.suite.add(new Option("No results in this view", ""));
        }
        controls.suite.disabled = scopes.length < 2;
        resetFilters();
        render();
    }

    function updateOptions(select, values, allLabel, labels = {}) {
        const previous = select.value;
        const options = [new Option(allLabel, "")];
        for (const value of values) {
            options.push(new Option(Object.hasOwn(labels, value) ? labels[value] : value, value));
        }
        select.replaceChildren(...options);
        select.value = values.includes(previous) ? previous : "";
    }

    function distinct(items, field) {
        return [...new Set(items.map((section) => section.dataset[field]))]
            .sort((left, right) => left.localeCompare(right));
    }

    function updateComparisons(section) {
        const selector = section.querySelector(".baseline-select");
        const baseline = selector.value || selector.options[0]?.value || "";
        for (const row of section.querySelectorAll("tr[data-result-id]")) {
            const comparison = data.comparisons[row.dataset.resultId]?.[baseline];
            const value = row.querySelector("[data-speedup]");
            const reason = row.querySelector("[data-comparison-reason]");
            if (comparison && Number.isFinite(comparison.speedup) && comparison.speedup > 0) {
                value.textContent = ratioFormat.format(comparison.speedup) + "×" +
                    (row.dataset.resultId === baseline ? " baseline" : "");
                reason.textContent = "";
            } else {
                value.textContent = "Unavailable";
                reason.textContent = comparison?.reason || "No baseline selected.";
            }
        }
    }

    function render() {
        let matching = sections.filter((section) =>
            section.dataset.scope === controls.suite.value
        );
        updateOptions(controls.dataset, distinct(matching, "dataset"), "All datasets");
        matching = matching.filter((section) =>
            !controls.dataset.value || section.dataset.dataset === controls.dataset.value
        );
        updateOptions(controls.query, distinct(matching, "query"), "All queries");
        matching = matching.filter((section) =>
            !controls.query.value || section.dataset.query === controls.query.value
        );
        const phases = ["cold", "warm", "warmup", "legacy"].filter((phase) =>
            matching.some((section) => section.dataset.phase === phase)
        );
        updateOptions(controls.phase, phases, "All phases", phaseLabels);
        matching = matching.filter((section) =>
            !controls.phase.value || section.dataset.phase === controls.phase.value
        );
        const visible = new Set(matching);
        let resultCount = 0;
        for (const section of sections) {
            section.hidden = !visible.has(section);
            if (!section.hidden) {
                updateComparisons(section);
                resultCount += section.querySelectorAll("tr[data-result-id]").length;
            }
        }
        empty.hidden = matching.length > 0;
        status.textContent = `${resultCount} result${resultCount === 1 ? "" : "s"} in ` +
            `${matching.length} section${matching.length === 1 ? "" : "s"}.`;
        if (scopeSummary) {
            const scope = data.scopes.find((item) => item.id === controls.suite.value);
            scopeSummary.textContent = scope ? scope.label : "No recorded results in this view.";
        }
    }

    for (const section of sections) {
        section.querySelector(".baseline-select").addEventListener("change", () =>
            updateComparisons(section)
        );
    }
    controls.view.addEventListener("change", selectScope);
    controls.suite.addEventListener("change", () => {
        resetFilters();
        render();
    });
    for (const control of [controls.dataset, controls.query, controls.phase]) {
        control.addEventListener("change", render);
    }
    controls.view.value = data.latest_scope ? "latest" :
        (scopesFor("history").length ? "history" :
            (scopesFor("legacy").length ? "legacy" : "latest"));
    selectScope();
})();
