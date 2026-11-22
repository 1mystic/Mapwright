from mapwright import analyze as A
from mapwright import render


def model(files):
    parts = {rel: A.analyze_file(rel, t) for rel, t in files.items() if A.analyze_file(rel, t)}
    return A.link(parts)


def paths(m):
    return {(r["path"], r["handler"]) for r in m["routes"]}


def test_object_route_table_with_children_and_index():
    m = model({
        "src/router.tsx": "import { createBrowserRouter } from 'react-router';\nimport { Home } from './Home';\nimport { Team } from './Team';\n"
                          "export const router = createBrowserRouter([\n"
                          "  { path: '/', element: <Layout />, children: [\n"
                          "    { index: true, element: <Home /> },\n"
                          "    { path: 'team', element: <Provider><Team /></Provider> },\n"
                          "    { path: 'team/:id', lazy: () => import('./Member').then((m) => ({ Component: m.Member })) },\n"
                          "  ] },\n"
                          "  { path: '/login', Component: Login },\n"
                          "]);\n",
        "src/Home.tsx": "export function Home() { return <div/>; }\n",
    })
    assert paths(m) == {("/", "Layout"), ("/", "Home"), ("/team", "Team"), ("/team/:id", "Member"), ("/login", "Login")}
    assert all(r["method"] == "PAGE" for r in m["routes"])
    home = next(r for r in m["routes"] if r["handler"] == "Home")
    assert home["fid"] == "src/Home:Home"


def test_route_array_and_lazy_group_dedupe():
    m = model({
        "src/shell/lazyRoutes.tsx": "import type { RouteObject } from 'react-router';\n"
                                    "export const lazyA = lazyGroup(() => import('../a/routes').then((m) => m.aRoutes), ['/a', '/a/:id']);\n",
        "src/a/routes.tsx": "import type { RouteObject } from 'react-router';\nimport { Page } from './Page';\n"
                            "export const aRoutes: RouteObject[] = [{ path: '/a', element: <Page /> }];\n",
    })
    got = {(r["path"], r["via"]) for r in m["routes"]}
    assert got == {("/a", "react-router"), ("/a/:id", "lazy-group")}


def test_jsx_routes_nested_paths():
    m = model({"src/App.tsx": "import { Routes, Route } from 'react-router-dom';\nexport function App() {\n  return (\n    <Routes>\n"
                              "      <Route element={<Guard />}>\n        <Route path=\"/signin\" element={<SignIn />} />\n      </Route>\n"
                              "      <Route path=\"/admin\" element={<Admin />}>\n        <Route index element={<Dash />} />\n"
                              "        <Route path=\"users\" element={<Users />} />\n      </Route>\n"
                              "      <Route path=\"*\" element={<NotFound />} />\n    </Routes>\n  );\n}\n"})
    assert paths(m) == {("/signin", "SignIn"), ("/admin", "Admin"), ("/admin", "Dash"), ("/admin/users", "Users"), ("/*", "NotFound")}


def test_non_router_objects_are_ignored():
    m = model({"src/cfg.ts": "export const x = [{ path: '/tmp', method: 'get' }];\n"})
    assert m["routes"] == []


def test_processes_view_lists_pages_and_react_tags():
    m = model({"src/App.tsx": "import { Route } from 'react-router';\nexport function App() { return <Route path=\"/x\" element={<X />} />; }\n"
                              "export function useThing() { return 1; }\n",
               "src/X.tsx": "export function X() { return <div />; }\n"})
    assert "PAGE /x" in render.processes(m)["mermaid"]
    assert m["functions"]["src/App:useThing"]["react"] == "hook"
    assert m["functions"]["src/X:X"]["react"] == "component"


def test_zod_schema_becomes_data_entity():
    m = model({"core/s.ts": "import { z } from 'zod';\nexport const Q = z.object({\n  id: z.string(),\n  marks: z.number().int(),\n});\n"})
    assert m["tables"]["Q"]["source"] == "zod" and [c["name"] for c in m["tables"]["Q"]["columns"]] == ["id", "marks"]
