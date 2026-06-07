#!/usr/bin/env python3
"""Interactive profile visualizer for the trailmix EC-add circuits.

Renders the per-circuit profile JSON dumped by `profile_ec_add_schrottenloher`
(run it with `PROFILE_JSON=1`) into a single self-contained HTML page with:

  - an occupancy envelope: live qubits over circuit time, colored by phase
    (built from the simulator's `live_series` + `section_marks`);
  - a leaf cost landscape: every leaf section as a bar, width = Toffoli,
    color = headroom (qubits below the global peak) -- red leaves sit *at* the
    peak and cannot be measure-vented, green leaves have room to spare;
  - the peak composition: which registers/roles occupy the qubit peak.

Usage
-----
    # 1. dump one or more configs (writes kmx_out/profile_<name>.json):
    cd trailmix
    PROFILE_JSON=1 PROFILE_NAME=jump-lowqubit cargo run --release \\
        --bin profile_ec_add_schrottenloher jump
    PROFILE_JSON=1 PROFILE_NAME=low-qubit cargo run --release \\
        --bin profile_ec_add_schrottenloher 5
    # 2. render (globs kmx_out/profile_*.json by default):
    cd ..
    python3 profile_viz.py                       # -> circuit_profiles.html
    python3 profile_viz.py out.html a.json b.json # explicit

No third-party Python deps (stdlib only); open the HTML in any browser.
"""
import glob
import json
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "circuit_profiles.html"
SRCS = sys.argv[2:]
if not SRCS:
    SRCS = sorted(glob.glob("kmx_out/profile_*.json")) or sorted(
        glob.glob("trailmix/kmx_out/profile_*.json")
    )
circuits = []
for s in SRCS:
    try:
        circuits.append(json.load(open(s)))
    except Exception as e:  # noqa: BLE001
        print(f"skip {s}: {e}", file=sys.stderr)
if not circuits:
    sys.exit(
        "no profile JSON found. Generate with "
        "`PROFILE_JSON=1 cargo run --release --bin profile_ec_add_schrottenloher <cfg>`"
    )

DATA_JSON = json.dumps(circuits)

PAGE = r"""<!doctype html><html><head><meta charset=utf8><title>trailmix circuit profiles</title>
<style>
 body{font:13px -apple-system,system-ui,sans-serif;margin:0;background:#0f1115;color:#dde}
 #wrap{padding:16px;max-width:1500px;margin:0 auto}
 h1{font-size:18px;margin:0 0 2px} .sub{color:#8a93a6;margin-bottom:12px}
 .tabs{display:flex;gap:8px;margin:10px 0}
 .tab{padding:6px 12px;border:1px solid #333a48;border-radius:6px;cursor:pointer;background:#1a1e27}
 .tab.on{background:#2a4d8f;border-color:#3a6fd0}
 .stat{display:inline-block;margin-right:18px} .stat b{color:#fff;font-size:15px}
 h2{font-size:14px;margin:18px 0 6px;color:#cfe} canvas{display:block;width:100%;background:#0a0c10;border:1px solid #262c38;border-radius:4px}
 #tip{position:fixed;pointer-events:none;background:#000d;border:1px solid #555;border-radius:4px;
   padding:6px 8px;font:12px monospace;display:none;z-index:9;white-space:pre;color:#fff}
 .leaf-row{display:flex;align-items:center;gap:8px;margin:2px 0;font:12px monospace}
 .leaf-name{width:230px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#cdd}
 .leaf-bar{height:15px;border-radius:2px} .leaf-meta{color:#9aa6bb;white-space:nowrap}
 .legend{display:flex;flex-wrap:wrap;gap:4px 12px;margin:6px 0;font-size:11px;color:#aab}
 .legend b{display:inline-block;width:10px;height:10px;margin-right:3px;vertical-align:-1px}
 .note{color:#8a93a6;font-size:12px;margin:4px 0 0}
</style></head><body><div id=wrap>
<h1>trailmix &mdash; reversible EC point-add circuit profiles</h1>
<div class=sub>secp256k1 in-place P += Q. Profiles dumped from the in-house simulator (64 shots). Hover for detail.</div>
<div class=tabs id=tabs></div>
<div id=stats class=sub></div>
<h2>Occupancy envelope &mdash; live qubits over circuit time (colored by phase)</h2>
<div class=legend id=phlegend></div>
<canvas id=env height=300></canvas>
<div class=note id=envnote></div>
<h2>Leaf cost landscape &mdash; Toffoli, local-peak &amp; headroom (the attack surface)</h2>
<div class=note>Bar width = Toffoli. Color = headroom (qubits below the global peak): <span style="color:#e0564b">red = at the peak, can't vent</span> &rarr; <span style="color:#3fbf6f">green = headroom to spare (measure-uncompute saves Toffoli without raising peak)</span>. ADDER leaves are the ventable ones.</div>
<div id=leaves></div>
<h2>Peak composition &mdash; what occupies the qubit peak</h2>
<div id=peakcomp></div>
</div><div id=tip></div>
<script>
const C = __DATA__;
let cur = 0;
const tip = document.getElementById('tip');
function phaseOf(path){ const s = path.split('/'); return s[2] || s[s.length-1] || path; }
function phaseColor(p){ let h=0; for(const c of p) h=(h*31+c.charCodeAt(0))%360; const [r,g,b]=hls(h/360,0.56,0.52); return `rgb(${r},${g},${b})`; }
function hls(h,l,s){ const f=(n)=>{const k=(n+h*12)%12;const a=s*Math.min(l,1-l);return Math.round(255*(l-a*Math.max(-1,Math.min(k-3,Math.min(9-k,1)))));}; return [f(0),f(8),f(4)]; }
function html_esc(s){ return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function renderTabs(){
  const t=document.getElementById('tabs'); t.innerHTML='';
  C.forEach((c,i)=>{ const d=document.createElement('div'); d.className='tab'+(i===cur?' on':''); d.textContent=c.config; d.onclick=()=>{cur=i;renderAll();}; t.appendChild(d); });
}
function renderStats(){
  const c=C[cur];
  document.getElementById('stats').innerHTML =
    `<span class=stat>peak qubits <b>${c.peak_qubits}</b></span>`+
    `<span class=stat>avg Toffoli <b>${c.total_tof.toLocaleString()}</b></span>`+
    `<span class=stat>total ops <b>${c.total_ops.toLocaleString()}</b></span>`+
    `<span class=stat>peak at op <b>${c.peak_at_op.toLocaleString()}</b> (${phaseOf(c.peak_section)})</span>`;
}
function bucketPhases(c){
  const NB=c.envelope.length, last=c.last_op, tl=c.timeline;
  const ph=new Array(NB); let ti=0, curp=tl.length?tl[0][1]:'';
  for(let b=0;b<NB;b++){
    const op=Math.round(b*last/(NB-1));
    while(ti+1<tl.length && tl[ti+1][0]<=op){ti++;}
    ph[b]=tl[ti]?tl[ti][1]:curp;
  }
  return ph;
}
function renderEnv(){
  const c=C[cur], cv=document.getElementById('env'), x=cv.getContext('2d');
  const W=cv.clientWidth||1400, H=300; cv.width=W; cv.height=H;
  const NB=c.envelope.length, peak=c.peak_qubits, pad=30, ph=bucketPhases(c);
  x.fillStyle='#0a0c10'; x.fillRect(0,0,W,H);
  const yOf=(v)=>H-pad-(v/peak)*(H-2*pad);
  for(let b=0;b<NB;b++){
    const px=b*W/NB, pw=Math.ceil(W/NB)+1;
    x.fillStyle=phaseColor(phaseOf(ph[b]));
    x.fillRect(px, yOf(c.envelope[b]), pw, H-pad-yOf(c.envelope[b]));
  }
  x.strokeStyle='#fff8'; x.setLineDash([5,4]); x.beginPath(); x.moveTo(0,yOf(peak)+.5); x.lineTo(W,yOf(peak)+.5); x.stroke();
  x.setLineDash([2,6]); x.strokeStyle='#fff2';
  for(let v=256;v<peak;v+=256){ x.beginPath(); x.moveTo(0,yOf(v)+.5); x.lineTo(W,yOf(v)+.5); x.stroke(); }
  x.setLineDash([]); x.fillStyle='#fff'; x.font='11px monospace'; x.fillText('peak '+peak, 4, yOf(peak)-3);
  for(let v=256;v<peak;v+=256){ x.fillStyle='#fff7'; x.fillText(''+v, 4, yOf(v)-2); }
  const seen=new Set(), order=[];
  for(const p of ph){ const k=phaseOf(p); if(!seen.has(k)){seen.add(k);order.push(k);} }
  document.getElementById('phlegend').innerHTML = order.map(p=>`<span><b style="background:${phaseColor(p)}"></b>${html_esc(p)}</span>`).join('');
  document.getElementById('envnote').textContent = `x = circuit time (${c.total_ops.toLocaleString()} ops, ${NB} buckets). The flat band near the top is where the peak is set; dips are where qubits free between phases.`;
  cv.onmousemove=(e)=>{ const r=cv.getBoundingClientRect(); const b=Math.floor((e.clientX-r.left)/r.width*NB); if(b<0||b>=NB){tip.style.display='none';return;}
    const op=Math.round(b*c.last_op/(NB-1));
    tip.textContent=`op ~${op.toLocaleString()}\nlive qubits: ${c.envelope[b]}\nphase: ${phaseOf(ph[b])}\nsection: ${ph[b]}`;
    tip.style.display='block'; tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY+14)+'px'; };
  cv.onmouseleave=()=>tip.style.display='none';
}
function headColor(h, peak){ const t=Math.max(0,Math.min(1,h/Math.max(1,peak*0.35))); const [r,g,b]=hls(t*0.33,0.5,0.6); return `rgb(${r},${g},${b})`; }
function renderLeaves(){
  const c=C[cur], box=document.getElementById('leaves'); box.innerHTML='';
  const maxtof=Math.max(...c.leaves.map(l=>l.tof));
  for(const l of c.leaves.slice(0,22)){
    const row=document.createElement('div'); row.className='leaf-row';
    const pct=(100*l.tof/c.total_tof).toFixed(1), w=Math.max(2,560*l.tof/maxtof);
    row.innerHTML=`<span class=leaf-name title="${html_esc(l.leaf)}">${html_esc(l.leaf)}</span>`+
      `<span class=leaf-bar style="width:${w}px;background:${headColor(l.headroom,c.peak_qubits)}"></span>`+
      `<span class=leaf-meta>${l.tof.toLocaleString()} tof (${pct}%) &middot; local-peak ${l.local_peak} &middot; headroom ${l.headroom} &middot; ${l.kind}</span>`;
    box.appendChild(row);
  }
}
function renderPeakComp(){
  const c=C[cur], box=document.getElementById('peakcomp'), g={};
  for(const t of c.peak_tags){ let k=t.includes('[')?t.slice(0,t.indexOf('[')):(t.includes('/')?t.split('/')[0]:t); g[k]=(g[k]||0)+1; }
  const rows=Object.entries(g).sort((a,b)=>b[1]-a[1]), mx=Math.max(...rows.map(r=>r[1]));
  box.innerHTML = `<div class=note>${c.peak_tags.length} qubits live at peak (${c.peak_qubits}), grouped by register/role:</div>`+
    rows.map(([k,n])=>`<div class=leaf-row><span class=leaf-name>${html_esc(k)}</span><span class=leaf-bar style="width:${Math.max(2,560*n/mx)}px;background:#3a6fd0"></span><span class=leaf-meta>${n} qubits</span></div>`).join('');
}
function renderAll(){ renderTabs(); renderStats(); renderEnv(); renderLeaves(); renderPeakComp(); }
window.addEventListener('resize', renderEnv);
renderAll();
</script></body></html>"""

with open(OUT, "w") as f:
    f.write(PAGE.replace("__DATA__", DATA_JSON))
print(f"wrote {os.path.abspath(OUT)}  ({len(circuits)} circuits: {', '.join(c['config'] for c in circuits)})")
