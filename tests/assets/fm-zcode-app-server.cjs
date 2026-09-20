#!/usr/bin/env node
/* External ZCode app-server protocol fixture, not a mock of the ACP bridge.
 * Based on the pinned zcode-acp docs/PROTOCOL.md; logs requests for assertions.
 * No provider key, network request, workspace edit or model inference occurs.
 */
const fs = require('node:fs');
const readline = require('node:readline');
const crypto = require('node:crypto');
const log = process.env.FLEET_ZCODE_FIXTURE_LOG;
if (!log) throw new Error('FLEET_ZCODE_FIXTURE_LOG is required');
if (process.argv.includes('--version')) { console.log('zcode fixture 3.12.0'); process.exit(0); }
const store = log + '.sessions.json';
const sessions = fs.existsSync(store) ? JSON.parse(fs.readFileSync(store, 'utf8')) : {};
const save = () => fs.writeFileSync(store, JSON.stringify(sessions));
const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
const result = (id, value) => { if (id !== undefined) emit({id, result: value}); };
function snapshot(id) {
  const item = sessions[id] || {};
  return {session: {sessionId: id, title: item.title || '', workspace: item.workspace},
    projection: {status: item.running ? 'running' : 'idle', contextUsed: 0, contextWindow: 200000},
    settings: {mode: {current: 'yolo'}, model: {current: {providerId: 'zai', modelId: 'GLM-5.2'}}, thoughtLevel: {current: 'high'}},
    messages: [], todos: []};
}
function event(id, type, payload = {}) {
  const item = sessions[id];
  if (!item) return;
  item.seq = (item.seq || 0) + 1;
  emit({method: 'session/event', params: {sessionId: id, seq: item.seq, type, payload}});
}
readline.createInterface({input: process.stdin}).on('line', line => {
  let request;
  try { request = JSON.parse(line); } catch { return; }
  fs.appendFileSync(log, JSON.stringify(request) + '\n');
  const {id, method, params = {}} = request;
  const sid = params.sessionId;
  if (method === 'session/create') {
    const created = 'fixture-' + crypto.randomUUID();
    sessions[created] = {workspace: params.workspace, seq: 0, running: false}; save();
    result(id, snapshot(created));
  } else if (method === 'session/resume') {
    if (!sessions[sid]) { emit({id, error: {code: -32002, message: 'fixture session missing'}}); return; }
    result(id, snapshot(sid));
  } else if (method === 'session/read') {
    result(id, snapshot(sid));
  } else if (method === 'session/list') {
    result(id, {sessions: Object.keys(sessions).map(key => snapshot(key).session)});
  } else if (method === 'session/subscribe') {
    result(id, {eventSeq: sessions[sid]?.seq || 0, snapshot: snapshot(sid)});
  } else if (method === 'session/messages') {
    result(id, {messages: [], hasMore: false});
  } else if (method === 'session/send') {
    if (!sessions[sid]) { emit({id, error: {code: -32002, message: 'unknown fixture session'}}); return; }
    sessions[sid].running = true; save();
    result(id, {accepted: true});
    const text = typeof params.content === 'string' ? params.content : JSON.stringify(params.content);
    setTimeout(() => {
      event(sid, 'turn.started');
      if (text.startsWith('WAIT')) return;
      event(sid, 'model.streaming', {kind: 'text_delta', delta: 'RECEIVED:' + text});
      sessions[sid].running = false;
      event(sid, 'turn.completed', {resultType: 'success'}); save();
    }, 20);
  } else if (method === 'session/stop') {
    if (sessions[sid]) { sessions[sid].running = false; event(sid, 'turn.completed', {resultType: 'cancelled'}); save(); }
    result(id, {});
  } else if (id !== undefined) {
    result(id, {});
  }
});
