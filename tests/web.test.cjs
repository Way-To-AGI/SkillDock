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
