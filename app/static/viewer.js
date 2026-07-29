import * as THREE from 'three';
import { STLLoader } from '/static/vendor/STLLoader.js';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

let renderer, scene, camera, controls, mesh, inited=false;
function initViewer(){
  const canvas = document.getElementById('viewerCanvas');
  renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1, 2));
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 8000);
  camera.up.set(0,0,1);                       // STL ist Z-oben
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.09;
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const d1 = new THREE.DirectionalLight(0xffffff, 0.95); d1.position.set(1, -1.4, 2.2); scene.add(d1);
  const d2 = new THREE.DirectionalLight(0xffffff, 0.45); d2.position.set(-1.2, 0.8, -1); scene.add(d2);
  inited = true;
  (function loop(){ requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
}
function resize(){
  const c = document.getElementById('viewerCanvas');
  const w = c.clientWidth||800, h = c.clientHeight||500;
  renderer.setSize(w, h, false); camera.aspect = w/h; camera.updateProjectionMatrix();
}
window.openSTLViewer = function(arrayBuffer, title){
  const modal = document.getElementById('viewerModal');
  document.getElementById('viewerTitle').textContent = title || 'STL';
  modal.style.display = 'flex';
  if(!inited) initViewer();
  resize();
  if(mesh){ scene.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); mesh=null; }
  const geo = new STLLoader().parse(arrayBuffer);
  geo.computeVertexNormals(); geo.center();
  const mat = new THREE.MeshPhongMaterial({color:0x9aa7b8, specular:0x2a3340, shininess:22});
  mesh = new THREE.Mesh(geo, mat); scene.add(mesh);
  geo.computeBoundingSphere();
  const r = geo.boundingSphere.radius || 30;
  camera.position.set(r*0.35, -r*1.9, r*1.15);
  camera.near = r/100; camera.far = r*40; camera.updateProjectionMatrix();
  controls.target.set(0,0,0); controls.update();
  resize();
};
window.closeSTLViewer = function(){ document.getElementById('viewerModal').style.display = 'none'; };
window.addEventListener('resize', ()=>{
  if(inited && document.getElementById('viewerModal').style.display !== 'none') resize();
});
document.getElementById('viewerModal').addEventListener('click', e=>{
  if(e.target.id === 'viewerModal') window.closeSTLViewer();
});
