const test = require("node:test"),
  assert = require("node:assert/strict"),
  fs = require("node:fs"),
  vm = require("node:vm"),
  path = require("node:path");
const base = path.join(__dirname, "..");
for (const name of ["app/web/app.js", "desktop.cjs", "preload.cjs"])
  test("JavaScript compiles: " + name, () => {
    new vm.Script(fs.readFileSync(path.join(base, name), "utf8"), {
      filename: name,
    });
  });
const source = fs.readFileSync(path.join(base, "app/web/app.js"), "utf8");
const core = source.slice(0, source.search(/^\$\(["']#create["']\)\.onclick/m));
function context() {
  const ctx = vm.createContext({
    console,
    window: {},
    document: { querySelector: () => null },
    fetch: async () => {
      throw Error("unexpected network");
    },
    setTimeout,
  });
  vm.runInContext(core, ctx);
  return ctx;
}
test("Escaping prevents skill content becoming HTML", () => {
  const ctx = context();
  assert.equal(
    vm.runInContext(`esc('<script>"&')`, ctx),
    "&lt;script&gt;&quot;&amp;",
  );
});
test("Same-name copies group without losing paths", () => {
  const ctx = context();
  vm.runInContext(
    `records=[{name:'demo',description:'a',id:'1',path:'/one'},{name:'demo',description:'b',id:'2',path:'/two'}]`,
    ctx,
  );
  assert.equal(vm.runInContext("groups().length", ctx), 1);
  assert.equal(vm.runInContext("groups()[0].copies.length", ctx), 2);
});
test("API sends mutation header and reports server error", async () => {
  const ctx = context();
  let options;
  ctx.fetch = async (url, o) => {
    options = o;
    return { ok: false, json: async () => ({ error: "conflict" }) };
  };
  await assert.rejects(
    vm.runInContext(`api('/api/create',{})`, ctx),
    /conflict/,
  );
  assert.equal(options.headers["X-SkillDock"], "1");
  assert.equal(options.credentials, "same-origin");
});
test("Readonly linked skill removable; readonly system not removable", () => {
  const ctx = context();
  assert.equal(
    vm.runInContext("removable({readonly:true,linked:true})", ctx),
    true,
  );
  assert.equal(
    vm.runInContext("removable({readonly:true,linked:false})", ctx),
    false,
  );
});
test("Finder action includes readonly local copies and escapes IDs; remote has none", () => {
  const ctx = context();
  for (const flags of [{}, { readonly: true }, { readonly: true, linked: true }]) {
    ctx.record = { id: 'id"<&', ...flags };
    const html = vm.runInContext("finderAction(record)", ctx);
    assert.match(html, /data-reveal-skill="id&quot;&lt;&amp;"/);
    assert.match(html, /在 Finder 中显示/);
  }
  assert.equal(vm.runInContext("finderAction({remote:true})", ctx), "");
});
test("Finder click targets the selected copy, prevents repeat clicks and preserves editor", async () => {
  const ctx = context();
  const button = { dataset: { revealSkill: "copy-two" }, disabled: false };
  ctx.container = { querySelectorAll: () => [button] };
  let request, complete;
  ctx.fetch = async (url, options) => {
    request = { url, options };
    await new Promise(resolve => { complete = resolve; });
    return { ok: true, json: async () => ({ message: "已在 Finder 中显示" }) };
  };
  const messages = [];
  ctx.recordMessage = message => messages.push(message);
  vm.runInContext('notify=recordMessage; activeId="original"; dirty=true; detailTab="source"; bindFinderActions(container)', ctx);
  const pending = button.onclick();
  assert.equal(button.disabled, true);
  assert.equal(request.url, "/api/reveal");
  assert.deepEqual(JSON.parse(request.options.body), { id: "copy-two" });
  complete();
  await pending;
  assert.equal(button.disabled, false);
  assert.deepEqual(messages, ["已在 Finder 中显示"]);
  assert.equal(vm.runInContext("activeId", ctx), "original");
  assert.equal(vm.runInContext("dirty", ctx), true);
  assert.equal(vm.runInContext("detailTab", ctx), "source");
});
test("Finder failures notify the user and re-enable the button", async () => {
  const ctx = context();
  const button = { dataset: { revealSkill: "missing" }, disabled: false };
  ctx.container = { querySelectorAll: () => [button] };
  ctx.fetch = async () => ({ ok: false, json: async () => ({ error: "技能不存在" }) });
  const messages = [];
  ctx.recordMessage = message => messages.push(message);
  vm.runInContext("notify=recordMessage; bindFinderActions(container)", ctx);
  await button.onclick();
  assert.deepEqual(messages, ["技能不存在"]);
  assert.equal(button.disabled, false);
});
test("Both installation overview and source detail include and bind Finder actions", () => {
  assert.match(source, /\$\{finderAction\(r\)\}/);
  assert.match(source, /\$\{finderAction\(x\)\}/);
  assert.match(source, /before\(overview\);\s+bindFinderActions\(panel\)/);
});
