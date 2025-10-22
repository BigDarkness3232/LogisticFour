/*! barcode_scanner.js – componente reutilizable con ZXing + Quagga */
(function () {
  const ZXING_URL = "https://unpkg.com/@zxing/library@0.21.3";
  const QUAGGA_URL = "https://unpkg.com/quagga2@1.8.4/dist/quagga.js";
  const ROI_RATIO = 0.32, LIVE_INTERVAL_MS = 550, SCALE_MAX_W = 1200, FALLBACK_EVERY = 4;

  // ---------- Utils ----------
  function loadScriptOnce(src){ return new Promise((ok,ko)=> {
    if (document.querySelector(`script[src^="${src}"]`)) return ok();
    const s=document.createElement('script'); s.src=src; s.onload=ok; s.onerror=ko; document.head.appendChild(s);
  });}
  function ensureLibs(){ return Promise.all([loadScriptOnce(ZXING_URL), loadScriptOnce(QUAGGA_URL)]); }
  function qs(sel,root=document){ return root.querySelector(sel); }
  function qsa(sel,root=document){ return [...root.querySelectorAll(sel)]; }
  function show(el,msg,ok=true){ el.classList.remove('d-none','alert-info','alert-danger','alert-success'); el.classList.add(ok?'alert-success':'alert-danger'); el.textContent=msg; }
  function info(el,msg){ el.classList.remove('d-none','alert-success','alert-danger'); el.classList.add('alert-info'); el.textContent=msg; }
  function hide(el){ el.classList.add('d-none'); }

  // ---------- Modal template (inyectado on-demand) ----------
  const STYLE = `
.bs-cam{position:relative;border-radius:16px;overflow:hidden;background:#0b0b0b}
.bs-vid{width:100%;height:100%;object-fit:cover;background:#000}
.bs-overlay{position:absolute;inset:0;pointer-events:none;display:none}
.bs-mask{position:absolute;inset:0;background:
  linear-gradient(to bottom,rgba(0,0,0,.5) calc((100% - 32%)/2),transparent calc((100% - 32%)/2),transparent calc((100% + 32%)/2),rgba(0,0,0,.5) calc((100% + 32%)/2)),
  linear-gradient(to right,rgba(0,0,0,.18) 6%,transparent 6%,transparent 94%,rgba(0,0,0,.18) 94%)}
.bs-frame{position:absolute;left:6%;right:6%;top:calc((100% - 32%)/2);height:32%;border:2px dashed rgba(255,255,255,.8);border-radius:12px}
.bs-corner{position:absolute;width:28px;height:28px;border:3px solid #0ea5e9;filter:drop-shadow(0 0 4px rgba(0,0,0,.6))}
.bs-tl{left:calc(6% - 3px);top:calc((100% - 32%)/2 - 3px);border-right:none;border-bottom:none}
.bs-tr{right:calc(6% - 3px);top:calc((100% - 32%)/2 - 3px);border-left:none;border-bottom:none}
.bs-bl{left:calc(6% - 3px);bottom:calc((100% - 32%)/2 - 3px);border-right:none;border-top:none}
.bs-br{right:calc(6% - 3px);bottom:calc((100% - 32%)/2 - 3px);border-left:none;border-top:none}
.bs-beam{position:absolute;left:6%;right:6%;height:2px;background:linear-gradient(90deg,transparent,#fff,transparent);mix-blend-mode:screen;opacity:.9;animation:bs-sweep 2.3s linear infinite}
@keyframes bs-sweep{0%{top:calc((100% - 32%)/2 + 2px)}100%{top:calc((100% + 32%)/2 - 2px)}}

/* Botones flotantes: desactivados para que no se superpongan */
.bs-fab{ display:none !important; }

/* Barra de controles (FUERA del video) */
.bs-controls{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin-top:.5rem}
.bs-controls .form-select{min-width:180px}
.bs-controls .form-range{flex:1 1 160px;max-width:360px}
`;

  const MODAL_HTML = `
<div class="modal fade" id="barcodeModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered modal-fullscreen-sm-down" style="max-width:950px">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="bsTitle">Escanear código</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
      </div>

      <div class="modal-body">
        <!-- VIDEO -->
        <div class="ratio ratio-16x9 bs-cam" id="bsCamBox">
          <video id="bsVideo" class="bs-vid" playsinline muted></video>

          <div class="bs-overlay" id="bsOverlay">
            <div class="bs-mask"></div>
            <div class="bs-frame"></div>
            <div class="bs-corner bs-tl"></div><div class="bs-corner bs-tr"></div>
            <div class="bs-corner bs-bl"></div><div class="bs-corner bs-br"></div>
            <div class="bs-beam"></div>
          </div>

          <!-- (oculto por CSS) botones flotantes antiguos -->
          <div class="bs-fab">
            <button id="bsFlip" class="btn btn-light btn-sm" title="Cambiar cámara">↺</button>
            <button id="bsFull" class="btn btn-light btn-sm" title="Pantalla completa">⛶</button>
            <button id="bsTorch" class="btn btn-warning btn-sm d-none" title="Linterna">💡</button>
          </div>
        </div>

        <!-- CONTROLES (fuera del video) -->
        <div class="bs-controls">
          <select id="bsCamera" class="form-select form-select-sm"></select>
          <input id="bsZoom" type="range" class="form-range d-none" min="1" max="1" step="0.1" />
          <div class="ms-auto d-flex flex-wrap gap-2">
            <button id="bsPreview" class="btn btn-outline-secondary btn-sm">Vista previa</button>
            <button id="bsLive" class="btn btn-primary btn-sm">En vivo</button>
            <button id="bsShot" class="btn btn-outline-info btn-sm">Capturar</button>
            <button id="bsPause" class="btn btn-outline-secondary btn-sm" disabled>Pausar</button>
            <button id="bsRestart" class="btn btn-outline-dark btn-sm" disabled>Reiniciar</button>

            <!-- NUEVOS controles (antes flotantes) -->
            <button id="bsFlipBar"  class="btn btn-outline-secondary btn-sm" title="Cambiar cámara">↺</button>
            <button id="bsFullBar"  class="btn btn-outline-secondary btn-sm" title="Pantalla completa">⛶</button>
            <button id="bsTorchBar" class="btn btn-outline-warning  btn-sm d-none" title="Linterna">💡</button>
          </div>
        </div>

        <div id="bsResult" class="alert alert-info d-none mt-2"></div>

        <!-- Subida de imagen -->
        <details class="mt-3">
          <summary class="small text-muted">Subir imagen</summary>
          <div class="row g-2 align-items-end mt-1">
            <div class="col-8">
              <input id="bsFile" type="file" accept="image/*" class="form-control">
              <small id="bsFileName" class="text-muted d-block mt-1">Ningún archivo seleccionado.</small>
            </div>
            <div class="col-4 d-flex gap-2">
              <button id="bsReadImg" class="btn btn-outline-primary w-100" disabled>Leer</button>
              <button id="bsClearImg" class="btn btn-outline-secondary">Limpiar</button>
            </div>
          </div>
          <img id="bsPreviewImg" class="img-fluid rounded d-none mt-2" alt="Vista previa">
          <div id="bsResultImg" class="alert alert-info d-none mt-2"></div>
        </details>
      </div>

      <div class="modal-footer">
        <small class="text-muted me-auto">FPS: <span id="bsFps">0</span> · Último intento: <code id="bsLast">—</code></small>
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
      </div>
    </div>
  </div>
</div>`;

  function ensureModal() {
    if (!qs('#barcodeModal')) {
      const s = document.createElement('style'); s.textContent = STYLE; document.head.appendChild(s);
      const d = document.createElement('div'); d.innerHTML = MODAL_HTML; document.body.appendChild(d.firstElementChild);
    }
  }

  // ---------- Decoders ----------
  function drawScaled(img,maxW){
    const sc=Math.min(1,maxW/img.width), w=Math.round(img.width*sc), h=Math.round(img.height*sc);
    const c=document.createElement('canvas'); c.width=w; c.height=h; c.getContext('2d').drawImage(img,0,0,w,h); return c;
  }
  function captureROIDataURL(vid){
    const vw=vid.videoWidth||1280, vh=vid.videoHeight||720, roiH=Math.floor(vh*ROI_RATIO), y=Math.floor((vh-roiH)/2);
    const c=document.createElement('canvas'); c.width=vw; c.height=roiH; c.getContext('2d').drawImage(vid,0,y,vw,roiH,0,0,vw,roiH);
    return c.toDataURL('image/png');
  }
  async function tryZXing(img,formats){
    try{
      const hints=new Map(); const set=[];
      (formats||[]).forEach(f=> ZXing.BarcodeFormat[f] && set.push(ZXing.BarcodeFormat[f]));
      if(set.length) hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS,set);
      hints.set(ZXing.DecodeHintType.TRY_HARDER,true);
      const reader=new ZXing.BrowserMultiFormatReader();
      const res=await reader.decodeFromImage(img,hints).catch(()=>null);
      if(!res) return null; return typeof res.getText==='function'? res.getText(): (res.text||null);
    }catch{ return null; }
  }
  function tryQuaggaFromCanvas(canvas){
    return new Promise(resolve=>{
      try{
        Quagga.decodeSingle({
          src: canvas.toDataURL('image/png'), numOfWorkers:0,
          inputStream:{ size:SCALE_MAX_W },
          decoder:{ readers:["ean_reader","ean_8_reader","upc_reader","upc_e_reader","code_128_reader","code_39_reader"] },
          locate:true
        }, r=> resolve(r && r.codeResult && r.codeResult.code ? r.codeResult.code : null));
      }catch{ resolve(null); }
    });
  }
  async function decodeDataURLTo(el,label,dataUrl,fast=false, liveAttemptRef={val:0}){
    try{
      info(el,`Procesando ${label}…`); qs('#bsLast').textContent=new Date().toLocaleTimeString();
      const img=await new Promise((ok,ko)=>{ const i=new Image(); i.onload=()=>ok(i); i.onerror=ko; i.src=dataUrl; });
      const canvas=drawScaled(img,SCALE_MAX_W);
      let code=await tryZXing(img,["EAN_13"]);
      if(code){ show(el,`Leído (${label}/ZXing): ${code}`,true); try{navigator.vibrate&&navigator.vibrate(25)}catch{}; return code; }
      const doWide=!fast || (fast && (liveAttemptRef.val % FALLBACK_EVERY===0));
      if(doWide){
        code=await tryZXing(img,["EAN_13","EAN_8","UPC_A","UPC_E","CODE_128","CODE_39"]);
        if(code){ show(el,`Leído (${label}/ZXing+): ${code}`,true); try{navigator.vibrate&&navigator.vibrate(25)}catch{}; return code; }
        const q=await tryQuaggaFromCanvas(canvas);
        if(q){ show(el,`Leído (${label}/Quagga): ${q}`,true); try{navigator.vibrate&&navigator.vibrate(25)}catch{}; return q; }
      }
      if(fast){ info(el,"Buscando… centra el código."); return null; }
      show(el,`No se pudo leer desde la ${label}.`,false); return null;
    }catch{ show(el,`Error procesando la ${label}.`,false); return null; }
  }

  // ---------- Core (instancia modal) ----------
  async function open(options={}){
    const { title="Escanear código", onScan=null, continuous=false, preferFacing='environment' } = options;
    await ensureLibs(); ensureModal();

    // refs
    const modalEl = qs('#barcodeModal');
    const titleEl = qs('#bsTitle');
    const video   = qs('#bsVideo');
    const overlay = qs('#bsOverlay');
    const camSel  = qs('#bsCamera');
    const zoom    = qs('#bsZoom');
    const resBox  = qs('#bsResult');
    const btnPrev = qs('#bsPreview');
    const btnLive = qs('#bsLive');
    const btnShot = qs('#bsShot');
    const btnPause= qs('#bsPause');
    const btnRestart = qs('#bsRestart');
    // flotantes (ocultos por CSS pero referenciados)
    const btnTorch = qs('#bsTorch');
    const btnFlip  = qs('#bsFlip');
    const btnFull  = qs('#bsFull');
    // barra inferior (nuevos)
    const btnTorchBar = qs('#bsTorchBar');
    const btnFlipBar  = qs('#bsFlipBar');
    const btnFullBar  = qs('#bsFullBar');

    const fpsEl = qs('#bsFps');

    const fInput = qs('#bsFile'), fName=qs('#bsFileName'), btnRead=qs('#bsReadImg'), btnClear=qs('#bsClearImg'),
          pImg=qs('#bsPreviewImg'), rImg=qs('#bsResultImg');

    // state
    let devs=[], currentDeviceId=null, track=null, liveTimer=null, fpsTimer=null, decoding=false;
    const liveAttemptRef = { val:0 };
    let _preferFacing = preferFacing;

    titleEl.textContent = title;

    function setBtns(previewOn){ btnRestart.disabled=previewOn; btnPause.disabled=!liveTimer; }
    function stopLive(){ if(liveTimer){ clearInterval(liveTimer); liveTimer=null; } btnPause.disabled=true; }
    function setupTorch(){
      const buttons = [btnTorch, btnTorchBar].filter(Boolean);
      if(!track || !track.getCapabilities){ buttons.forEach(b=>b.classList.add('d-none')); return; }
      const caps=track.getCapabilities(); const vis = 'torch' in caps;
      buttons.forEach(b=> b.classList.toggle('d-none', !vis));
    }
    function setupZoom(){
      if(!track || !track.getCapabilities) return zoom.classList.add('d-none');
      const caps=track.getCapabilities();
      if('zoom' in caps){ zoom.min=caps.zoom.min||1; zoom.max=caps.zoom.max||1; zoom.step=caps.zoom.step||0.1; zoom.value=track.getSettings().zoom||zoom.min; zoom.classList.remove('d-none'); }
      else zoom.classList.add('d-none');
    }
    async function applyZoom(v){ try{ await track.applyConstraints({ advanced:[{ zoom:Number(v) }] }); }catch{} }

    async function ensureReady(vid){ return new Promise(res=>{ if(vid.readyState>=2 && vid.videoWidth) return res(); const f=()=>{ if(vid.videoWidth){ vid.removeEventListener('loadedmetadata',f); res(); } }; vid.addEventListener('loadedmetadata',f); requestAnimationFrame(f); }); }

    async function listCameras(){
      try{ const s=await navigator.mediaDevices.getUserMedia({video:true}); s.getTracks().forEach(t=>t.stop()); }catch{}
      const all=await navigator.mediaDevices.enumerateDevices();
      devs=all.filter(d=>d.kind==='videoinput');
      camSel.innerHTML='';
      devs.forEach((d,i)=>{ const o=document.createElement('option'); o.value=d.deviceId||''; o.textContent=d.label||`Cámara ${i+1}`; camSel.appendChild(o); });
      if(!currentDeviceId && devs[0]) currentDeviceId=devs[0].deviceId||null;
    }

    function getConstraints(){
      if(currentDeviceId) return { video:{ deviceId:{exact:currentDeviceId}, width:{ideal:1920}, height:{ideal:1080}, focusMode:"continuous" } };
      return { video:{ facingMode:{ideal:_preferFacing}, width:{ideal:1920}, height:{ideal:1080}, focusMode:"continuous" } };
    }

    async function startPreview(){
      stopLive(); hide(resBox);
      try{
        const stream=await navigator.mediaDevices.getUserMedia(getConstraints());
        video.srcObject=stream; await video.play(); await ensureReady(video);
        track=stream.getVideoTracks()[0]||null; overlay.style.display='';
        setupTorch(); setupZoom(); setBtns(true);

        clearInterval(fpsTimer); let last=performance.now();
        fpsTimer=setInterval(()=>{ const now=performance.now(); const fps=1000/(now-last); fpsEl.textContent=isFinite(fps)?fps.toFixed(1):'0'; last=now; },1000);
      }catch(e){
        console.error(e); show(resBox, "No se pudo iniciar la cámara. Revisa permisos o usa HTTPS.", false);
        overlay.style.display='none';
      }
    }
    function stopPreview(){
      overlay.style.display='none'; stopLive();
      if(video.srcObject){ video.srcObject.getTracks().forEach(t=>t.stop()); video.srcObject=null; track=null; }
      [btnTorch, btnTorchBar].forEach(b=> b && b.classList.add('d-none'));
      zoom.classList.add('d-none'); clearInterval(fpsTimer);
      setBtns(false);
    }

    // eventos cámara
    camSel.onchange = e => { currentDeviceId=e.target.value||null; _preferFacing='environment'; startPreview(); };
    btnPrev.onclick = startPreview;
    btnRestart.onclick = async()=>{ stopPreview(); await startPreview(); };

    btnLive.onclick = async()=>{
      if(!video.srcObject) await startPreview(); await ensureReady(video);
      if(liveTimer) return; liveAttemptRef.val=0; btnPause.disabled=true; setTimeout(()=>btnPause.disabled=false,400);
      liveTimer=setInterval(async()=>{
        if(decoding) return; decoding=true;
        try{
          const dataUrl=captureROIDataURL(video);
          const code=await decodeDataURLTo(resBox,'captura',dataUrl,true, liveAttemptRef);
          liveAttemptRef.val++;
          if(code){
            if (typeof onScan === 'function') onScan(code);
            if (!continuous) { stopLive(); const m = bootstrap.Modal.getOrCreateInstance(modalEl); m.hide(); }
          }
        } finally { decoding=false; }
      }, LIVE_INTERVAL_MS);
    };
    btnPause.onclick = ()=> stopLive();

    btnShot.onclick = async ()=>{
      if(!video.srcObject) await startPreview(); await ensureReady(video);
      const dataUrl=captureROIDataURL(video);
      const code=await decodeDataURLTo(resBox,'captura',dataUrl,false, liveAttemptRef);
      if(code && typeof onScan==='function'){ onScan(code); if(!continuous){ const m=bootstrap.Modal.getOrCreateInstance(modalEl); m.hide(); } }
    };

    // Torch/Flip/Full: mismos handlers para flotantes (ocultos) y para barra
    const torchHandler = async ()=>{ if(!track) return; const s=track.getSettings(); const on=!s.torch; try{ await track.applyConstraints({ advanced:[{ torch:on }] }); }catch{} };
    [qs('#bsTorch'), qs('#bsTorchBar')].forEach(b=> b && (b.onclick = torchHandler));

    const flipHandler = async ()=>{ _preferFacing = (_preferFacing==='environment')?'user':'environment'; currentDeviceId=null; await startPreview(); };
    [qs('#bsFlip'), qs('#bsFlipBar')].forEach(b=> b && (b.onclick = flipHandler));

    const fullHandler = ()=> { const el=qs('#bsCamBox'); if(!document.fullscreenElement){ el.requestFullscreen?.(); } else { document.exitFullscreen?.(); } };
    [qs('#bsFull'), qs('#bsFullBar')].forEach(b=> b && (b.onclick = fullHandler));

    zoom.addEventListener('input', e=> applyZoom(e.target.value));

    qs('#bsCamBox').addEventListener('click', async (e)=>{
      if(!track || !track.getCapabilities) return;
      const caps=track.getCapabilities(); if(!('pointsOfInterest' in caps)) return;
      const r=e.currentTarget.getBoundingClientRect(); const x=(e.clientX-r.left)/r.width, y=(e.clientY-r.top)/r.height;
      try{ await track.applyConstraints({ advanced:[{ pointsOfInterest:[{x,y}] }] }); }catch{}
    });

    // subir imagen
    fInput.addEventListener('change', ()=>{
      hide(rImg);
      const f=fInput.files&&fInput.files[0];
      if(!f){ fName.textContent='Ningún archivo seleccionado.'; pImg.classList.add('d-none'); btnRead.disabled=true; return; }
      fName.textContent=f.name;
      const rd=new FileReader();
      rd.onload=(ev)=>{ const dataUrl=ev.target.result; pImg.src=dataUrl; pImg.classList.remove('d-none'); btnRead.disabled=false; decodeImageDataURL(dataUrl); };
      rd.readAsDataURL(f);
    });
    btnRead.onclick = ()=>{
      const f=fInput.files&&fInput.files[0]; if(!f){ show(rImg,'Primero selecciona una imagen.',false); return; }
      const rd=new FileReader(); rd.onload=(e)=>decodeImageDataURL(e.target.result); rd.readAsDataURL(f);
    };
    btnClear.onclick = ()=>{ fInput.value=''; fName.textContent='Ningún archivo seleccionado.'; pImg.classList.add('d-none'); pImg.src=''; hide(rImg); btnRead.disabled=true; };
    async function decodeImageDataURL(d){
      const code = await decodeDataURLTo(rImg,'imagen',d,false, liveAttemptRef);
      if(code && typeof onScan==='function'){ onScan(code); if(!continuous){ const m=bootstrap.Modal.getOrCreateInstance(modalEl); m.hide(); } }
    }

    // abrir modal
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl, { backdrop:'static' });
    modalEl.addEventListener('shown.bs.modal', async ()=>{ await listCameras(); await startPreview(); qs('#bsOverlay').style.display=''; });
    modalEl.addEventListener('hidden.bs.modal', ()=>{ stopPreview(); });
    modal.show();
  }

  // Helper para inputs: al escanear, llena el input y dispara change
  function attachToInput(inputSelector, options={}){
    const input = document.querySelector(inputSelector);
    if(!input) return console.warn('attachToInput: input no encontrado', inputSelector);
    const { buttonSelector=null, continuous=false, preferFacing='environment' } = options;

    const launcher = ()=> open({
      continuous,
      preferFacing,
      onScan: (code)=>{ input.value = code; input.dispatchEvent(new Event('change',{bubbles:true})); }
    });

    if(buttonSelector){
      const btn = document.querySelector(buttonSelector);
      if(btn) btn.addEventListener('click', launcher);
    }
    return { open: launcher };
  }

  // Exponer API global
  window.BarcodeScanner = { open, attachToInput };
})();
