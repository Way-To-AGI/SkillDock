let smartView = "all",
  originFilter = "",
  detailTab = "overview",
  initialOpened = false;
let scanReport = {},
  records = [],
  roots = [],
  trash = [],
  query = "",
  agent = "",
  selected = new Set(),
  activeId = null,
  activeRemote = null,
  dirty = false,
  undoState = null,
  busy = false,
  loadSerial = 0;
const $ = (s) => document.querySelector(s),
  esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const lock =
  '<span class="lock" title="只读"><svg width="11" height="12" viewBox="0 0 16 18" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="8" width="12" height="8" rx="2"/><path d="M5 8V5a3 3 0 0 1 6 0v3"/></svg></span>';
const writable = (r) => !r.readonly,
  removable = (r) => !r.readonly || r.linked;
function groups() {
  let map = new Map();
  for (let r of records) {
    if (!map.has(r.name)) map.set(r.name, []);
    map.get(r.name).push(r);
  }
  return [...map]
    .map(([name, copies]) => ({
      name,
      copies,
      description: copies[0].description,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}
function visible() {
  let q = query.trim().toLowerCase();
  return groups().filter(
    (g) =>
      (!agent || g.copies.some((r) => r.agent === agent)) &&
      (!q ||
        [g.name, g.description, ...g.copies.map((r) => r.agentLabel)]
          .join(" ")
          .toLowerCase()
          .includes(q)) &&
      matchesView(g, smartView) &&
      (!originFilter || scoped(g).some((r) => r.origin === originFilter)),
  );
}
function scoped(g) {
  return g.copies.filter((r) => !agent || r.agent === agent);
}
function renderToolbarCore() {
  const t = $("#toolbar");
  if (selected.size) {
    t.innerHTML = `<div class="batch"><span class="selection-count">已选 ${selected.size} 项</span><button id="batchCopy">复制到…</button><button id="batchDelete" class="danger">删除</button><button id="clearSelection" class="icon" aria-label="取消选择">×</button></div>`;
    $("#batchCopy").onclick = () => copyModal([...selected]);
    $("#batchDelete").onclick = () => deleteModal([...selected]);
    $("#clearSelection").onclick = () => {
      selected.clear();
      render();
    };
  } else {
    const labels = new Map();
    for (let r of records) labels.set(r.agent, r.agentLabel);
    t.innerHTML = `<label class="search"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg><input id="search" type="search" placeholder="搜索技能" aria-label="搜索技能" value="${esc(query)}"></label><select id="agent" aria-label="筛选 Agent"><option value="">所有 Agent</option>${[...labels].map(([id, label]) => `<option value="${esc(id)}" ${id === agent ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
    $("#search").oninput = (e) => {
      query = e.target.value;
      renderRows();
    };
    $("#agent").onchange = (e) => {
      agent = e.target.value;
      renderRows();
    };
  }
}
function renderRowsCore() {
  const list = visible(),
    current = records.find((r) => r.id === activeId);
  $("#rows").innerHTML = list.length
    ? list
        .map((g) => {
          let cs = scoped(g),
            labels = [...new Set(cs.map((r) => r.agentLabel))];
          return `<div class="row ${current?.name === g.name ? "active" : ""} ${selected.has(g.name) ? "selected" : ""}" data-name="${esc(g.name)}" tabindex="0" role="button" aria-label="打开 ${esc(g.name)}"><input type="checkbox" aria-label="选择 ${esc(g.name)}" ${selected.has(g.name) ? "checked" : ""}><div class="skill"><div class="name">${esc(g.name)}${cs.every((r) => r.readonly) ? lock : ""}</div><div class="desc">${esc(g.description || "暂无描述")}</div></div><div class="agents">${labels.map((label) => `<span class="tag">${esc(label)}</span>`).join("")}</div></div>`;
        })
        .join("")
    : '<div class="empty">没有匹配的技能</div>';
  for (let row of $("#rows").children) {
    if (!row.dataset.name) continue;
    row.onclick = () => openSkill(row.dataset.name);
    row.onkeydown = (e) => {
      if (e.key === "Enter") openSkill(row.dataset.name);
    };
    row.querySelector("input").onclick = (e) => {
      e.stopPropagation();
      let n = row.dataset.name;
      selected.has(n) ? selected.delete(n) : selected.add(n);
      render();
    };
  }
  const all = $("#selectAll");
  all.checked = list.length > 0 && list.every((g) => selected.has(g.name));
  all.indeterminate = list.some((g) => selected.has(g.name)) && !all.checked;
  $("#count").textContent =
    `${list.length} 项${query || agent ? " / " + groups().length + " 项" : ""}`;
}
function render() {
  renderNavigation();
  renderToolbar();
  renderRows();
}
async function api(path, body) {
  const options = { credentials: "same-origin" };
  if (body !== undefined)
    Object.assign(options, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-SkillDock": "1" },
      body: JSON.stringify(body),
    });
  const response = await fetch(path, options);
  let result;
  try {
    result = await response.json();
  } catch {
    throw Error("本地服务没有返回有效数据");
  }
  if (!response.ok) throw Error(result.error || "操作失败");
  return result;
}
async function refresh() {
  const state = await api("/api/state");
  records = state.skills.filter((r) => r.scope === "global");
  roots = state.roots
    .filter((r) => r.scope === "global")
    .sort(
      (a, b) =>
        Number(b.exists) - Number(a.exists) || a.label.localeCompare(b.label),
    );
  trash = state.trash;
  scanReport = state.discovery || {};
  const names = new Set(records.map((r) => r.name));
  selected = new Set([...selected].filter((n) => names.has(n)));
  render();
  if (!initialOpened && records.length) {
    initialOpened = true;
    const first = records.find((r) => r.name === "agent-reach") || records[0];
    openSkill(first.name);
  }
}
function leave() {
  if (busy) {
    notify("操作进行中，请稍等");
    return false;
  }
  if (dirty) {
    if (!confirm("放弃未保存的修改？")) return false;
    dirty = false;
    renderEditor();
  }
  return true;
}
async function openSkill(name, id) {
  if (!leave()) return;
  if (!id) detailTab = "overview";
  const g = groups().find((g) => g.name === name);
  if (!g) return;
  activeRemote = null;
  activeId =
    id || scoped(g).find(writable)?.id || scoped(g)[0]?.id || g.copies[0].id;
  const serial = ++loadSerial;
  const el = $("#editor");
  el.hidden = false;
  el.innerHTML = '<div class="loading">读取中…</div>';
  renderRows();
  try {
    const detail = await api("/api/skill?id=" + encodeURIComponent(activeId));
    if (serial !== loadSerial) return;
    Object.assign(records.find((r) => r.id === detail.id) || {}, detail);
    renderEditor();
  } catch (e) {
    if (serial === loadSerial) {
      activeId = null;
      el.hidden = true;
      notify(e.message);
      renderRows();
    }
  }
}
async function reloadEditor() {
  if (activeId) {
    const r = records.find((x) => x.id === activeId);
    if (r) {
      try {
        Object.assign(
          r,
          await api("/api/skill?id=" + encodeURIComponent(activeId)),
        );
      } catch (e) {
        activeId = null;
        notify(e.message);
      }
    } else activeId = null;
  }
  renderEditor();
}
function renderEditorCore() {
  const r = activeRemote || records.find((r) => r.id === activeId),
    el = $("#editor");
  if (!r) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  let copies = r.remote ? [r] : records.filter((x) => x.name === r.name);
  el.innerHTML = `<div class="editor-head"><span class="editor-title">${esc(r.name)} <span id="changed" class="badge"></span></span><button id="closeEditor" class="icon" aria-label="关闭编辑器">×</button></div><div class="location"><div class="location-top">${copies.length > 1 ? `<select id="locationSelect" aria-label="选择技能副本">${copies.map((x) => `<option value="${esc(x.id)}" ${x.id === r.id ? "selected" : ""}>${esc(x.agentLabel)}${x.readonly ? " · 只读" : ""}</option>`).join("")}</select>` : `<span>${esc(r.remote ? r.source : r.agentLabel)}</span>`}<span class="readonly">${r.remote ? "skills.sh" : r.readonly ? "只读" : ""}</span></div><div class="path">${esc(r.remote ? r.source + "/" + r.skillId : r.path + "/SKILL.md")}</div>${r.usedBy?.length > 1 ? `<div class="tiny">源文件被 ${esc(r.usedBy.join("、"))} 引用，保存会影响这些引用。</div>` : ""}${r.linked && r.canonicalId ? '<button id="editSource" class="link-button">编辑全局源文件 ↗</button>' : ""}</div><textarea class="document" id="content" spellcheck="false" aria-label="SKILL.md 内容" ${r.readonly ? "readonly" : ""}></textarea><div class="editor-actions">${r.remote ? '<button id="install" class="primary">安装到…</button>' : `${!r.readonly ? '<button id="save" class="primary" disabled>保存</button>' : ""}<button id="copy">复制到…</button><span class="spacer"></span>${removable(r) ? '<button id="delete" class="danger">删除</button>' : ""}`}</div>`;
  $("#content").value = r.content || "";
  $("#content").oninput = () => {
    dirty = $("#content").value !== r.content;
    $("#changed").textContent = dirty ? "未保存" : "";
    if ($("#save")) $("#save").disabled = !dirty;
  };
  $("#closeEditor").onclick = () => {
    if (leave()) {
      activeId = null;
      activeRemote = null;
      loadSerial++;
      el.hidden = true;
      renderRows();
    }
  };
  if ($("#locationSelect"))
    $("#locationSelect").onchange = (e) => openSkill(r.name, e.target.value);
  if ($("#save")) $("#save").onclick = save;
  if ($("#copy")) $("#copy").onclick = () => copyModal([r.name], r.id);
  if ($("#delete")) $("#delete").onclick = () => deleteModal([r.name], r.id);
  if ($("#editSource"))
    $("#editSource").onclick = () => {
      const source = records.find((x) => x.id === r.canonicalId);
      if (source) openSkill(source.name, source.id);
    };
  if ($("#install")) $("#install").onclick = () => installModal(r);
}
function notify(message, undoable = false) {
  $("#toastText").textContent = message;
  $("#undo").hidden = !undoable;
  $("#toast").hidden = false;
}
async function save() {
  const r = records.find((r) => r.id === activeId);
  if (!r || r.readonly || !dirty || busy) return;
  busy = true;
  const content = $("#content").value;
  $("#save").disabled = true;
  $("#content").disabled = true;
  try {
    await api("/api/update", { id: r.id, content, version: r.version });
    dirty = false;
    await refresh();
    await reloadEditor();
    notify("已保存 · 原版本已备份");
  } catch (e) {
    notify(e.message);
    $("#save").disabled = false;
  } finally {
    busy = false;
    if ($("#content")) $("#content").disabled = false;
  }
}
function modal(title, body, action, label = "确认") {
  const d = $("#dialog");
  d.classList.remove("wide");
  d.innerHTML = `<div class="modal-head"><h2>${esc(title)}</h2><button class="icon" id="modalClose" aria-label="关闭">×</button></div><div class="modal-body">${body}<p class="error" id="error"></p></div><div class="modal-actions"><button id="cancel">取消</button><button class="primary" id="confirm">${esc(label)}</button></div>`;
  $("#modalClose").onclick = $("#cancel").onclick = () => {
    if (!busy) d.close();
  };
  $("#confirm").onclick = async () => {
    if (busy) return;
    busy = true;
    const button = $("#confirm");
    button.disabled = true;
    $("#error").textContent = "";
    try {
      await action();
    } catch (e) {
      if ($("#error")) $("#error").textContent = e.message;
      else notify(e.message);
    } finally {
      busy = false;
      if (button.isConnected) button.disabled = false;
    }
  };
  if (!d.open) d.showModal();
}
function targetChoices() {
  const available = roots.filter((r) => !r.readonly),
    row = (r) =>
      `<label class="choice"><input type="checkbox" name="target" value="${esc(r.id)}"><span>${esc(r.label)}</span></label>`;
  const existing = available.filter((r) => r.exists),
    other = available.filter((r) => !r.exists);
  return (
    existing.map(row).join("") +
    (other.length
      ? `<details ${existing.length ? "" : "open"}><summary>其他 Agent 位置（${other.length}）</summary>${other.map(row).join("")}</details>`
      : "")
  );
}
function copyModal(names, sourceId) {
  if (!leave()) return;
  modal(
    names.length === 1 ? "复制技能" : "复制 " + names.length + " 项",
    `<p class="note">复制完整技能文件夹，已有同名目录会跳过。</p>${targetChoices()}`,
    async () => {
      const ids = [...document.querySelectorAll("[name=target]:checked")].map(
        (x) => x.value,
      );
      if (!ids.length) throw Error("请选择一个目标 Agent");
      let added = 0,
        skipped = 0,
        errors = [];
      for (let name of names) {
        const source =
          records.find((r) => r.id === sourceId && r.name === name) ||
          records.find(
            (r) =>
              r.name === name && (!agent || r.agent === agent) && writable(r),
          ) ||
          records.find(
            (r) => r.name === name && (!agent || r.agent === agent),
          ) ||
          records.find((r) => r.name === name);
        if (!source) continue;
        for (let rootId of ids) {
          if (
            records.some(
              (r) => r.rootId === rootId && r.folder === source.folder,
            )
          ) {
            skipped++;
            continue;
          }
          try {
            await api("/api/copy", {
              id: source.id,
              rootId,
              folder: source.folder,
            });
            added++;
          } catch (e) {
            errors.push(name + "：" + e.message);
          }
        }
      }
      selected.clear();
      await refresh();
      await reloadEditor();
      if (errors.length)
        throw Error(
          `已复制 ${added} 份，跳过 ${skipped} 份。${errors.join("；")}`,
        );
      $("#dialog").close();
      notify(
        `已复制 ${added} 份${skipped ? " · 跳过 " + skipped + " 份同名目录" : ""}`,
      );
    },
    "复制",
  );
}
function deleteModal(names, id) {
  if (!leave()) return;
  let cs = records.filter(
    (r) => names.includes(r.name) && (!agent || r.agent === agent),
  );
  if (id) cs = records.filter((r) => r.id === id);
  modal(
    "删除技能",
    `<p class="note">移入回收站，可随时恢复。</p>${cs.map((r) => `<label class="choice"><input type="checkbox" name="deleteCopy" value="${esc(r.id)}" ${removable(r) ? "checked" : "disabled"}><span>${esc(r.name)}<br><small>${esc(r.agentLabel)}${removable(r) ? "" : " · 只读"}</small><div class="path">${esc(r.path)}</div></span></label>`).join("")}`,
    async () => {
      const ids = [
        ...document.querySelectorAll("[name=deleteCopy]:checked"),
      ].map((x) => x.value);
      if (!ids.length) throw Error("请选择可删除的副本");
      const removed = [],
        errors = [];
      for (let id of ids) {
        try {
          const result = await api("/api/delete", { id });
          removed.push(result.trashId);
        } catch (e) {
          errors.push(e.message);
        }
      }
      if (removed.length) undoState = removed;
      selected.clear();
      await refresh();
      await reloadEditor();
      if (errors.length) {
        notify(`已删除 ${removed.length} 份`, removed.length > 0);
        throw Error(errors.join("；"));
      }
      $("#dialog").close();
      notify(`已删除 ${removed.length} 份`, removed.length > 0);
    },
    "删除",
  );
  $("#confirm").classList.replace("primary", "danger");
}
async function undoDelete() {
  if (!undoState || !leave()) return;
  busy = true;
  const remaining = [],
    errors = [];
  for (let id of undoState) {
    try {
      await api("/api/restore", { id });
    } catch (e) {
      remaining.push(id);
      errors.push(e.message);
    }
  }
  undoState = remaining.length ? remaining : null;
  try {
    await refresh();
    await reloadEditor();
    notify(errors.length ? errors.join("；") : "已恢复", !!undoState);
  } catch (e) {
    notify(e.message);
  } finally {
    busy = false;
  }
}
function newSkill() {
  if (!leave()) return;
  detailTab = "source";
  modal(
    "新建技能",
    `<label class="field">名称<input id="newName" placeholder="my-skill" autocomplete="off"></label><label class="field">描述<input id="newDescription" placeholder="这个技能用来做什么"></label><label class="field">Agent<select id="newRoot">${roots
      .filter((r) => !r.readonly)
      .map(
        (r) =>
          `<option value="${esc(r.id)}" ${r.agent === agent ? "selected" : ""}>${esc(r.label)}</option>`,
      )
      .join("")}</select></label>`,
    async () => {
      const name = $("#newName").value.trim(),
        description = $("#newDescription").value.trim(),
        root = roots.find((r) => r.id === $("#newRoot").value);
      if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$/.test(name))
        throw Error(
          "名称需以字母或数字开头，使用字母、数字、点、短横线或下划线",
        );
      if (!description) throw Error("请填写技能描述");
      if (!root) throw Error("请先添加 Agent 目录");
      const result = await api("/api/create", {
        rootId: root.id,
        folder: name,
        content:
          "---\nname: " +
          JSON.stringify(name) +
          "\ndescription: " +
          JSON.stringify(description) +
          "\n---\n\n# " +
          name +
          "\n\n",
      });
      $("#dialog").close();
      query = "";
      agent = root.agent;
      selected.clear();
      activeRemote = null;
      activeId = result.id;
      await refresh();
      await reloadEditor();
      notify("已创建");
      $("#content")?.focus();
    },
    "创建",
  );
  $("#newName").focus();
}
function trashModal() {
  if (!leave()) return;
  modal(
    "回收站",
    trash.length
      ? trash
          .map(
            (r) =>
              `<div class="trash-row"><div><strong>${esc(r.name)}</strong><span class="tiny">${esc(r.agentLabel)}</span><div class="path">${esc(r.original)}</div></div><button data-restore="${esc(r.id)}">恢复</button></div>`,
          )
          .join("")
      : '<p class="note">回收站是空的</p>',
    () => $("#dialog").close(),
    "完成",
  );
  $("#confirm").hidden = true;
  $("#cancel").textContent = "关闭";
  $("#dialog").classList.add("wide");
  for (let b of document.querySelectorAll("[data-restore]"))
    b.onclick = async () => {
      if (busy) return;
      busy = true;
      b.disabled = true;
      try {
        await api("/api/restore", { id: b.dataset.restore });
        if (undoState)
          undoState = undoState.filter((x) => x !== b.dataset.restore);
        await refresh();
        busy = false;
        trashModal();
        notify("已恢复");
      } catch (e) {
        $("#error").textContent = e.message;
      } finally {
        busy = false;
        if (b.isConnected) b.disabled = false;
      }
    };
}
function directoryModal() {
  if (!leave()) return;
  const ordered = [...roots].sort(
    (a, b) =>
      Number(b.discovery === "heuristic") -
        Number(a.discovery === "heuristic") ||
      Number(b.exists) - Number(a.exists) ||
      a.label.localeCompare(b.label),
  );
  const row = (r) =>
    `<div class="root-row"><div><strong>${esc(r.label)}${r.readonly ? " · 只读" : ""}</strong><div class="tiny">${r.discovery === "heuristic" ? "按 SKILL.md 结构发现，确认后可编辑" : esc((r.supportedAgents || []).join(" / "))}${r.exists ? "" : " · 尚未建立"}</div><div class="path">${esc(r.path)}</div></div>${r.discovery === "heuristic" ? `<button data-confirm-root="${esc(r.id)}">确认管理</button>` : ""}<button data-show-root="${esc(r.id)}" ${r.exists ? "" : "disabled"}>打开</button>${!r.builtin ? `<button class="danger" data-remove-root="${esc(r.id)}">移除</button>` : ""}</div>`;
  const present = ordered.filter(
      (r) => r.exists || r.discovery === "heuristic",
    ),
    absent = ordered.filter((r) => !r.exists && r.discovery !== "heuristic");
  modal(
    "全局 Agent 目录",
    `<div class="modal-search"><p class="note">${scanReport.catalogAgents || 0} 类 Agent 目录规则 · ${scanReport.pending || 0} 个待确认${scanReport.truncated ? " · 扫描达到上限，可手动添加" : ""}</p><button id="scanRoots">重新扫描</button></div>${present.map(row).join("")}<details><summary>其他已知位置（${absent.length}）</summary>${absent.map(row).join("")}</details>`,
    () => addRootModal(),
    "添加目录",
  );
  $("#dialog").classList.add("wide");
  $("#scanRoots").onclick = async () => {
    if (busy) return;
    busy = true;
    try {
      await api("/api/discover", {});
      await refresh();
      busy = false;
      directoryModal();
      notify("目录扫描完成");
    } catch (e) {
      $("#error").textContent = e.message;
    } finally {
      busy = false;
    }
  };
  for (let b of document.querySelectorAll("[data-show-root]"))
    b.onclick = () =>
      api("/api/reveal", { rootId: b.dataset.showRoot }).catch((e) =>
        notify(e.message),
      );
  for (let b of document.querySelectorAll("[data-confirm-root]"))
    b.onclick = async () => {
      if (busy) return;
      busy = true;
      try {
        await api("/api/roots/confirm", { id: b.dataset.confirmRoot });
        await refresh();
        busy = false;
        directoryModal();
        notify("已确认，可以管理此目录");
      } catch (e) {
        $("#error").textContent = e.message;
      } finally {
        busy = false;
      }
    };
  for (let b of document.querySelectorAll("[data-remove-root]"))
    b.onclick = async () => {
      if (busy || !confirm("从管理列表移除此目录？磁盘文件保留。")) return;
      busy = true;
      b.disabled = true;
      try {
        await api("/api/roots/remove", { id: b.dataset.removeRoot });
        await refresh();
        busy = false;
        directoryModal();
      } catch (e) {
        $("#error").textContent = e.message;
      } finally {
        busy = false;
        if (b.isConnected) b.disabled = false;
      }
    };
}
function addRootModal() {
  modal(
    "添加 Agent 目录",
    '<label class="field">名称<input id="rootLabel" placeholder="我的 Agent"></label><label class="field">全局 skills 目录<input id="rootPath" placeholder="~/.my-agent/skills"></label><button id="browseRoot">选择文件夹</button><label class="choice"><input id="rootReadonly" type="checkbox">只读</label>',
    async () => {
      await api("/api/roots/add", {
        label: $("#rootLabel").value.trim(),
        path: $("#rootPath").value.trim(),
        readonly: $("#rootReadonly").checked,
        scope: "global",
      });
      await refresh();
      $("#dialog").close();
      notify("目录已添加");
    },
    "添加",
  );
  $("#browseRoot").onclick = async () => {
    const path = await window.skilldock?.chooseDirectory();
    if (path) $("#rootPath").value = path;
  };
}
let marketSerial = 0;
function discovery() {
  if (!leave()) return;
  modal(
    "发现技能",
    '<form class="modal-search" id="marketForm"><input id="marketQuery" placeholder="搜索 skills.sh" aria-label="搜索 skills.sh"><button type="submit">搜索</button></form><div id="marketResults"><p class="note">输入技能名称或用途。</p></div>',
    () => $("#dialog").close(),
    "完成",
  );
  $("#confirm").hidden = true;
  $("#cancel").textContent = "关闭";
  $("#dialog").classList.add("wide");
  $("#marketForm").onsubmit = async (e) => {
    e.preventDefault();
    const q = $("#marketQuery").value.trim();
    if (!q) return;
    const serial = ++marketSerial;
    $("#marketResults").innerHTML = '<div class="loading">搜索中…</div>';
    try {
      const result = await api("/api/search?q=" + encodeURIComponent(q));
      if (serial !== marketSerial || !$("#marketResults")) return;
      $("#marketResults").innerHTML = result.skills.length
        ? result.skills
            .map(
              (r, i) =>
                `<div class="market-row"><div><strong>${esc(r.name)}</strong><div class="tiny">${esc(r.source)} · ${Number(r.installs || 0).toLocaleString()} 次安装</div></div><button data-market="${i}">${r.installable ? "查看" : "来源 ↗"}</button></div>`,
            )
            .join("")
        : '<p class="note">没有找到匹配技能。</p>';
      for (let b of document.querySelectorAll("[data-market]"))
        b.onclick = () => openRemote(result.skills[Number(b.dataset.market)]);
    } catch (e) {
      if (serial === marketSerial && $("#marketResults"))
        $("#marketResults").innerHTML =
          `<p class="note error">${esc(e.message)}</p>`;
    }
  };
  $("#marketQuery").focus();
}
async function openRemote(item) {
  if (!item.installable) {
    window.open(item.url, "_blank", "noopener");
    return;
  }
  if (busy) return;
  busy = true;
  try {
    const detail = await api("/api/preview", {
      source: item.source,
      skillId: item.skillId,
    });
    $("#dialog").close();
    activeId = null;
    loadSerial++;
    activeRemote = { ...detail, remote: true, readonly: true };
    renderEditor();
    renderRows();
  } catch (e) {
    if ($("#error")) $("#error").textContent = e.message;
    else notify(e.message);
  } finally {
    busy = false;
  }
}
function installModal(item) {
  modal(
    "安装技能",
    `<p class="note">${esc(item.name)} · 包含 ${item.files.length} 个文件</p>${targetChoices()}`,
    async () => {
      const rootIds = [
        ...document.querySelectorAll("[name=target]:checked"),
      ].map((x) => x.value);
      if (!rootIds.length) throw Error("请选择目标 Agent");
      const result = await api("/api/install", {
        source: item.source,
        skillId: item.skillId,
        folder: item.skillId,
        rootIds,
      });
      await refresh();
      $("#dialog").close();
      notify(result.message);
    },
    "安装",
  );
}
$("#create").onclick = newSkill;
$("#selectAll").onclick = () => {
  let list = visible(),
    on = $("#selectAll").checked;
  for (let g of list) on ? selected.add(g.name) : selected.delete(g.name);
  render();
};
$("#dismiss").onclick = () => ($("#toast").hidden = true);
$("#undo").onclick = undoDelete;
$("#dialog").onclick = (e) => {
  if (!busy && e.target === $("#dialog")) {
    let box = e.target.getBoundingClientRect();
    if (
      e.clientX < box.left ||
      e.clientX > box.right ||
      e.clientY < box.top ||
      e.clientY > box.bottom
    )
      e.target.close();
  }
};
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "s") {
    e.preventDefault();
    if (dirty) save();
  }
  if (e.key === "Escape" && !$("#dialog").open && (activeId || activeRemote)) {
    if (leave()) {
      activeId = null;
      activeRemote = null;
      loadSerial++;
      renderEditor();
      renderRows();
    }
  }
  if (
    e.key === "/" &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) &&
    !$("#dialog").open
  ) {
    e.preventDefault();
    selected.clear();
    renderToolbar();
    $("#search").focus();
  }
});
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});

$("#more").onclick = () => ($("#menu").hidden = !$("#menu").hidden);
document.addEventListener("click", (e) => {
  if (!e.target.closest(".header-actions")) $("#menu").hidden = true;
});
for (let [id, fn] of [
  ["discover", discovery],
  ["directories", directoryModal],
  ["trashMenu", trashModal],
  [
    "refresh",
    () => {
      if (!leave()) return;
      refresh()
        .then(() => reloadEditor())
        .then(() => notify("已刷新"))
        .catch((e) => notify(e.message));
    },
  ],
]) {
  $("#" + id).onclick = () => {
    $("#menu").hidden = true;
    fn();
  };
}
$("#dialog").addEventListener("cancel", (e) => {
  if (busy) e.preventDefault();
});

function matchesView(g, v) {
  return (
    v === "all" ||
    (v === "editable" && g.copies.some(writable)) ||
    (v === "multi" && new Set(g.copies.map((r) => r.agent)).size > 1) ||
    (v === "issues" &&
      (g.copies.some((r) => !r.valid) ||
        new Set(g.copies.map((r) => r.version)).size > 1))
  );
}
function renderNavigation() {
  const gs = groups(),
    views = [
      ["all", "▦", "全部技能"],
      ["editable", "✎", "可编辑"],
      ["multi", "⇄", "多 Agent"],
      ["issues", "◉", "需检查"],
    ];
  $("#smartViews").innerHTML = views
    .map(
      ([id, glyph, title]) =>
        `<button data-view="${id}" class="${smartView === id && !agent ? "current" : ""}"><span class="nav-symbol">${glyph}</span>${title}<small>${gs.filter((g) => matchesView(g, id)).length}</small></button>`,
    )
    .join("");
  for (let b of document.querySelectorAll("[data-view]"))
    b.onclick = () => {
      smartView = b.dataset.view;
      agent = "";
      query = "";
      originFilter = "";
      selected.clear();
      render();
    };
  const ids = new Map();
  for (let r of records) if (!ids.has(r.agent)) ids.set(r.agent, r.agentLabel);
  $("#agentNavigation").innerHTML = [...ids]
    .map(
      ([id, title]) =>
        `<button data-navigation-agent="${esc(id)}" class="${agent === id ? "current" : ""}"><span class="agent-dot"></span>${esc(title.replace(" 缓存", ""))}<small>${gs.filter((g) => g.copies.some((r) => r.agent === id)).length}</small></button>`,
    )
    .join("");
  for (let b of document.querySelectorAll("[data-navigation-agent]"))
    b.onclick = () => {
      agent = b.dataset.navigationAgent;
      smartView = "all";
      query = "";
      originFilter = "";
      selected.clear();
      render();
    };
  $("#sideTrashCount").textContent = trash.length || "";
  $("#viewTitle").textContent = agent
    ? ids.get(agent) || "Agent 技能"
    : views.find((v) => v[0] === smartView)[2];
  $("#viewDescription").textContent = agent
    ? "管理这个 Agent 的全局技能与独立副本。"
    : "统一查看技能、安装分布与各 Agent 的独立副本。";
  $("#summary").textContent =
    `${gs.length} 项技能 · ${records.length} 个安装位置`;
}
function renderToolbar() {
  renderToolbarCore();
  $("#sourceFilters").innerHTML = [
    ["", "全部来源"],
    ["local", "个人技能"],
    ["system", "内置"],
    ["plugin", "插件"],
  ]
    .map(
      ([id, label]) =>
        `<button data-origin="${id}" class="${originFilter === id ? "current" : ""}">${label}</button>`,
    )
    .join("");
  for (let b of document.querySelectorAll("[data-origin]"))
    b.onclick = () => {
      originFilter = b.dataset.origin;
      selected.clear();
      renderToolbar();
      renderRows();
    };
}
function renderRows() {
  renderRowsCore();
  for (let row of $("#rows").children) {
    if (!row.dataset.name) continue;
    const g = groups().find((g) => g.name === row.dataset.name);
    let issue =
        g.copies.some((r) => !r.valid) ||
        new Set(g.copies.map((r) => r.version)).size > 1,
      edit = scoped(g).some(writable);
    const state = document.createElement("span");
    state.className = "row-state " + (issue ? "issue" : edit ? "editable" : "");
    state.textContent = issue ? "需检查" : edit ? "可编辑" : "只读";
    row.append(state);
  }
  if ($("#smartViews")) renderNavigation();
}
function renderEditor() {
  renderEditorCore();
  const r = activeRemote || records.find((r) => r.id === activeId);
  if (!r) return;
  const panel = $("#editor");
  const tabs = document.createElement("div");
  tabs.className = "detail-tabs";
  tabs.innerHTML = [
    ["overview", "安装分布"],
    ["source", r.readonly ? "SKILL.md" : "编辑内容"],
    ["files", "附件 " + (r.files?.length || 0)],
  ]
    .map(
      ([id, label]) =>
        `<button data-detail-tab="${id}" class="${detailTab === id ? "current" : ""}">${label}</button>`,
    )
    .join("");
  panel.querySelector(".editor-head").after(tabs);
  for (let b of tabs.querySelectorAll("button"))
    b.onclick = () => {
      detailTab = b.dataset.detailTab;
      applyDetailTab();
    };
  const overview = document.createElement("div");
  overview.className = "detail-overview";
  const copies = r.remote ? [r] : records.filter((x) => x.name === r.name);
  overview.innerHTML = `<p class="detail-description">${esc(r.description || "暂无描述")}</p><p class="detail-label">${r.remote ? "远程来源" : "已安装 " + copies.length + " 份"}</p>${copies.map((x) => `<div class="installation ${r.id === x.id ? "current" : ""}"><div class="installation-header"><span>${esc(x.remote ? x.source : x.agentLabel)}</span><small>${x.remote ? "GitHub" : x.linked ? "链接" : x.readonly ? "只读" : "可编辑"}</small></div><div class="path">${esc(x.remote ? x.source + "/" + x.skillId : x.path)}</div>${!x.remote ? `<button data-open-copy="${esc(x.id)}">${x.id === r.id ? "编辑此副本" : "打开此副本"} ↗</button>` : ""}</div>`).join("")}<div class="help-note">${r.remote ? "安装包含完整技能文件夹。" : r.usedBy?.length > 1 ? "当前源文件被 " + esc(r.usedBy.join("、")) + " 引用。" : "复制到其他 Agent 后成为独立副本；保存针对当前选中的路径。"}</div>`;
  panel.querySelector(".editor-actions").before(overview);
  for (let b of overview.querySelectorAll("[data-open-copy]"))
    b.onclick = () => {
      const x = records.find((x) => x.id === b.dataset.openCopy);
      if (!x) return;
      if (x.id === activeId) {
        detailTab = "source";
        applyDetailTab();
      } else {
        openSkill(x.name, x.id).then(() => {
          if (activeId === x.id) {
            detailTab = "source";
            applyDetailTab();
          }
        });
      }
    };
  const files = document.createElement("div");
  files.className = "detail-files";
  files.innerHTML = r.files?.length
    ? r.files
        .map(
          (f) =>
            `<div class="file-entry"><span>${esc(f.path)}</span><small>${f.size < 1024 ? f.size + " B" : (f.size / 1024).toFixed(1) + " KB"}</small></div>`,
        )
        .join("")
    : '<div class="help-note">没有附件。</div>';
  panel.querySelector(".editor-actions").before(files);
  applyDetailTab();
}
function applyDetailTab() {
  const panel = $("#editor");
  if (!panel.querySelector(".detail-tabs")) return;
  for (let b of panel.querySelectorAll("[data-detail-tab]"))
    b.classList.toggle("current", b.dataset.detailTab === detailTab);
  panel.querySelector(".location").hidden = detailTab !== "source";
  panel.querySelector(".document").hidden = detailTab !== "source";
  panel.querySelector(".detail-overview").hidden = detailTab !== "overview";
  panel.querySelector(".detail-files").hidden = detailTab !== "files";
  if ($("#save")) $("#save").hidden = detailTab !== "source";
}
$("#sideDiscover").onclick = discovery;
$("#sideTrash").onclick = trashModal;
$("#sideDirectories").onclick = $("#manageAgents").onclick = directoryModal;
const headerActions = $(".header-actions");
const find = document.createElement("button");
find.textContent = "发现技能";
find.onclick = discovery;
headerActions.prepend(find);
const reload = document.createElement("button");
reload.textContent = "↻";
reload.setAttribute("aria-label", "刷新技能目录");
reload.onclick = () => {
  if (leave())
    refresh()
      .then(() => reloadEditor())
      .then(() => notify("已刷新"))
      .catch((e) => notify(e.message));
};
headerActions.prepend(reload);

render();
refresh().catch((e) => notify(e.message));
