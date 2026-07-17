(function attachLayoutPlanner(root) {
  "use strict";

  const COLUMN_CAPACITY = 100;
  const COLUMN_NAMES = ["왼쪽", "오른쪽"];

  function visualUnits(text) {
    let total = 0;
    for (const char of String(text || "")) {
      if (/\s/u.test(char)) total += 1;
      else total += char.codePointAt(0) > 0xff ? 2 : 1;
    }
    return total;
  }

  function wrappedLineCount(text, limit) {
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    return lines.reduce((total, line) => total + Math.max(1, Math.ceil(visualUnits(line) / limit)), 0);
  }

  function tableHeight(tables, lineLimit) {
    let height = 0;
    for (const rows of tables || []) {
      if (!Array.isArray(rows) || !rows.length) continue;
      const columns = Math.max(1, ...rows.map((row) => (Array.isArray(row) ? row.length : 0)));
      const cellLimit = Math.max(12, Math.floor(lineLimit / columns));
      height += 4;
      for (const row of rows) {
        const rowLines = Math.max(
          1,
          ...(Array.isArray(row) ? row : []).map((cell) => wrappedLineCount(cell, cellLimit)),
        );
        height += 6 + rowLines * 4;
      }
    }
    return height;
  }

  function estimateProblemHeight(problem, template = {}) {
    const columns = Math.max(1, Math.min(Number(template.columns) || 1, 2));
    const lineLimit = columns > 1 ? 48 : 92;
    let height = 10;
    height += wrappedLineCount(problem?.stem || problem?.title || "문제", lineLimit) * 5;

    const choices = Array.isArray(problem?.choices) ? problem.choices : [];
    const inlineChoices = Boolean(template.inline_short_choices) && choices.join("").length <= 90;
    if (choices.length) {
      if (inlineChoices) height += wrappedLineCount(choices.join("　　"), lineLimit) * 5;
      else height += choices.reduce((sum, choice) => sum + wrappedLineCount(choice, lineLimit) * 5, 0);
    }

    height += tableHeight(problem?.tables, lineLimit);
    height += (problem?.image_paths?.length || 0) * 34;
    if (template.answer_blank && !choices.length) height += 6;
    if (template.include_answers && problem?.answer) height += 6;
    if (template.include_explanations && problem?.explanation) {
      height += wrappedLineCount(problem.explanation, lineLimit) * 5;
    }
    return Math.max(14, Math.round(height));
  }

  function slotPosition(slot, columns) {
    return {
      page: Math.floor(slot / columns) + 1,
      column: (slot % columns) + 1,
    };
  }

  function positionLabel(position, columns) {
    if (columns === 1) return `${position.page}쪽`;
    return `${position.page}쪽 · ${COLUMN_NAMES[position.column - 1]} 단`;
  }

  function planLayout(problems, template = {}) {
    const columns = Math.max(1, Math.min(Number(template.columns) || 1, 2));
    const placements = [];
    let slot = 0;
    let used = 0;

    (problems || []).forEach((problem, index) => {
      const height = estimateProblemHeight(problem, template);
      const oversized = height > COLUMN_CAPACITY;
      let breakBefore = false;
      if (used > 0 && (oversized || used + height > COLUMN_CAPACITY)) {
        slot += 1;
        used = 0;
        breakBefore = true;
      }

      const startSlot = slot;
      const start = slotPosition(startSlot, columns);
      let endSlot = startSlot;
      if (oversized) {
        const occupiedSlots = Math.max(1, Math.ceil(height / COLUMN_CAPACITY));
        endSlot = startSlot + occupiedSlots - 1;
        slot = endSlot;
        used = height % COLUMN_CAPACITY;
        if (!used) {
          slot += 1;
          used = 0;
        }
      } else {
        used += height;
      }

      const end = slotPosition(endSlot, columns);
      const tight = !oversized && height >= 82;
      const risk = oversized ? "split" : tight ? "tight" : "none";
      const startLabel = positionLabel(start, columns);
      const endLabel = positionLabel(end, columns);
      placements.push({
        index,
        id: problem?.id ?? null,
        estimatedHeight: height,
        fillPercent: Math.min(100, height),
        start,
        end,
        startSlot,
        endSlot,
        breakBefore,
        oversized,
        risk,
        label: oversized && endSlot !== startSlot ? `${startLabel} → ${endLabel}` : startLabel,
      });
    });

    const maxEndSlot = placements.reduce((max, item) => Math.max(max, item.endSlot), 0);
    const pageCount = placements.length ? Math.floor(maxEndSlot / columns) + 1 : 0;
    const pages = Array.from({ length: pageCount }, (_, pageIndex) => ({
      page: pageIndex + 1,
      columns: Array.from({ length: columns }, (_, columnIndex) => ({
        column: columnIndex + 1,
        items: [],
        continuations: [],
      })),
    }));
    for (const placement of placements) {
      pages[placement.start.page - 1]?.columns[placement.start.column - 1]?.items.push(placement.index);
      for (let occupiedSlot = placement.startSlot + 1; occupiedSlot <= placement.endSlot; occupiedSlot += 1) {
        const occupied = slotPosition(occupiedSlot, columns);
        pages[occupied.page - 1]?.columns[occupied.column - 1]?.continuations.push(placement.index);
      }
    }

    return {
      columns,
      capacity: COLUMN_CAPACITY,
      pageCount,
      placements,
      pages,
      warningCount: placements.filter((item) => item.risk !== "none").length,
      splitCount: placements.filter((item) => item.oversized).length,
    };
  }

  root.HwpLayoutPlanner = {
    COLUMN_CAPACITY,
    estimateProblemHeight,
    planLayout,
    visualUnits,
    wrappedLineCount,
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
