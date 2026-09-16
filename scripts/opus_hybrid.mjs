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
const api = async (path, body) => {
  const r = await fetch('https://api.opus.pro/api' + path, { method: body ? 'POST' : 'GET',
    headers: { Authorization: 'Bearer ' + KEY, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  if (!r.ok) throw new Error(`${path} -> ${r.status}: ${t.slice(0,300)}`);
  return JSON.parse(t);
};
// 复用已上传的源（UPL_hxZmSWdQyw），只喂 treg 选段区间，skip-slicing = 整段保留不再切
const proj = await api('/clip-projects', {
  videoUrl: 'UPL_hxZmSWdQyw',
  uploadedVideoAttr: { title: 'HYBRID test - treg segment our-selection their-render' },
  curationPref: { skipCurate: false, model: 'ClipAnything', range: { startSec: 2660, endSec: 2840 },
                  clipDurations: [[40, 70]] },
  renderPref: { layoutAspectRatio: 'landscape' },
  importPreference: { sourceLang: 'en' } });
fs.writeFileSync('opus_hybrid_project.json', JSON.stringify(proj, null, 1));
console.log('hybrid project:', proj.id);
