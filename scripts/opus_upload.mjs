import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Key lookup: process env first, then a dotenv file ($CLIP_FACTORY_ENV, ./.env, ~/.clip-factory.env).
const readKey = (name) => {
  if (process.env[name]) return process.env[name];
  const files = [process.env.CLIP_FACTORY_ENV, path.join(process.cwd(), '.env'),
                 path.join(os.homedir(), '.clip-factory.env')].filter(Boolean);
  for (const f of files) {
    try {
      const m = fs.readFileSync(f, 'utf8').match(new RegExp('^(?:export\\s+)?' + name + '=(\\S+)', 'm'));
      if (m) return m[1].replace(/^["']|["']$/g, '');
    } catch { /* next candidate */ }
  }
  throw new Error(`Missing ${name}: set it in the environment or in .env (see .env.example).`);
};
const KEY = readKey('OPUSCLIP_API_KEY');
const BASE = 'https://api.opus.pro/api';
const H = { Authorization: 'Bearer ' + KEY, 'Content-Type': 'application/json' };
const SRC = process.env.SRC; if (!SRC) throw new Error('SRC env required');

const api = async (path, body, method) => {
  const r = await fetch(BASE + path, { method: method || (body ? 'POST' : 'GET'),
    headers: H, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  if (!r.ok) throw new Error(`${path} -> ${r.status}: ${t.slice(0, 300)}`);
  try { return JSON.parse(t); } catch { return t; }
};

const buf = fs.readFileSync(SRC);
const sizeMb = Math.max(1, Math.ceil(buf.byteLength / 1048576));
let link = await api('/upload-links', { type: 'Upload', domain: 'Google', usecase: 'LocalUpload',
  extension: 'mp4', fileName: 'source.mp4', size: sizeMb });
link = link.data ?? link;
const uploadUrl = link.upload_url || link.url, uploadId = link.upload_id || link.uploadId;
console.log('step1 uploadId:', uploadId);

const init = await fetch(uploadUrl, { method: 'POST',
  headers: { 'x-goog-resumable': 'start', 'Content-Length': '0' } });
if (!init.ok) throw new Error('resumable init ' + init.status);
const session = init.headers.get('location');
console.log('step2 session ok');

const put = await fetch(session, { method: 'PUT',
  headers: { 'Content-Type': 'application/octet-stream' }, body: buf });
if (!put.ok) throw new Error('PUT ' + put.status + ': ' + (await put.text()).slice(0, 200));
console.log('step3 upload done', sizeMb, 'MB');

const proj = await api('/clip-projects', {
  videoUrl: uploadId,
  uploadedVideoAttr: { title: process.env.PROJECT_TITLE || 'clip-factory upload' },
  curationPref: {
    model: 'ClipAnything',
    clipDurations: [[40, 65]],
    customPrompt: 'Find self-contained segments that teach a transferable lesson for AI builders (agent patterns, workflows, judgments that outlive any single tool). Prefer moments with a quotable, contrarian or number-backed claim. Skip: product pitches by the speaker about their own product, multi-person crosstalk Q&A, demo failures, housekeeping.' },
  renderPref: { layoutAspectRatio: 'landscape' },
  importPreference: { sourceLang: 'en' } });
fs.writeFileSync('opus_project.json', JSON.stringify(proj, null, 1));
console.log('step4 project:', JSON.stringify(proj).slice(0, 300));
