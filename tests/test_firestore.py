from mapwright import analyze as A
from mapwright import render

RULES = """rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    function isOwner(uid) { return request.auth != null && request.auth.uid == uid; }
    match /users/{uid} {
      allow read: if isOwner(uid);
      allow create, update: if isOwner(uid)
        && request.resource.data.keys().hasOnly(['a']);
      allow delete: if false;
      match /notes/{noteId} {
        allow read, write: if isOwner(uid);   // trailing comment
      }
    }
    match /config/{docId} {
      allow get: if docId in ['a', 'b'];
    }
    match /{document=**} { allow read, write: if false; }
  }
}
"""

CODE = """import { collection, doc, getDocs, setDoc } from 'firebase/firestore';
export async function load(db, uid) {
  const snap = await getDocs(collection(db, 'users', uid, 'notes'));
  return snap;
}
export function save(db, id) { return setDoc(doc(db, 'config', id), {}); }
export const q = (db) => db.collection('papers').doc('p').collection('items');
export const g = (db) => collectionGroup(db, 'items');
"""


def model(files):
    return A.link({rel: A.analyze_file(rel, t) for rel, t in files.items()})


def test_rules_compose_paths_and_ops():
    t = model({"firestore.rules": RULES})["tables"]
    assert set(t) == {"firestore:users", "firestore:users/{id}/notes", "firestore:config"}
    assert t["firestore:users"]["ops"]["read"] == "isOwner(uid)"
    assert set(t["firestore:users"]["ops"]) == {"read", "create", "update", "delete"}
    assert t["firestore:users"]["ops"]["delete"] == "false"
    assert "hasOnly" in t["firestore:users"]["ops"]["create"]
    assert t["firestore:users/{id}/notes"]["columns"][0]["fk"] == "firestore:users"
    assert t["firestore:config"]["kind"] == "firestore" and t["firestore:config"]["source"] == "firestore rules"


def test_code_usage_merges_with_rules_and_links_functions():
    m = model({"firestore.rules": RULES, "src/db.ts": CODE})
    t = m["tables"]
    assert t["firestore:users/{id}/notes"]["source"] == "firestore rules" and "src/db.ts" in t["firestore:users/{id}/notes"]["also_in"]
    assert "firestore:papers/{id}/items" in t and "firestore:items" in t
    assert m["functions"]["src/db:load"]["tables"] == ["firestore:users/{id}/notes"]
    assert m["functions"]["src/db:save"]["tables"] == ["firestore:config"]


def test_erd_labels_firestore_collections():
    m = model({"firestore.rules": RULES, "src/db.ts": CODE})
    erd = render.erd(m, {})
    assert "firestore_users_id_notes" in erd["mermaid"] and 'rule read "isOwner(uid)"' in erd["mermaid"]
    assert "firestore_users ||--o{ firestore_users_id_notes" in erd["mermaid"]
    assert erd["nodes"]


def test_does_not_confuse_other_collection_calls():
    m = model({"src/x.ts": "const a = collection(ref, 'notes'); const b = db.other('x'); const c = collection(db, path);\n"})
    assert m["tables"] == {}


def test_storage_rules():
    m = model({"storage.rules": "service firebase.storage {\n match /b/{bucket}/o {\n match /avatars/{uid}/{all=**} {\n allow read: if true;\n }\n }\n}\n"})
    assert list(m["tables"]) == ["storage:avatars"] and m["tables"]["storage:avatars"]["kind"] == "storage"
