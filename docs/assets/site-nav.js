/* One floating island nav for every page. Usage:
   <div id="sitenav"></div><script src="<base>assets/site-nav.js" data-cur="test|audit|home" defer></script> */
(function(){
"use strict";
var me=document.currentScript||document.querySelector('script[src*="site-nav.js"]');
var BASE=me.src.replace(/assets\/site-nav\.js.*$/,""),CUR=me.getAttribute("data-cur")||"home";
var host=document.getElementById("sitenav");
if(!host){host=document.createElement("div");host.id="sitenav";document.body.insertBefore(host,document.body.firstChild)}
var I={
 test:'<rect x="2.5" y="3.5" width="19" height="17" rx="3.5"/><path d="M6.8 9.2l3 2.6-3 2.6M12.3 15.6h4.9"/>',
 audit:'<path d="M12.5 3H7a2.5 2.5 0 0 0-2.5 2.5v13A2.5 2.5 0 0 0 7 21h4.2"/><path d="M12.5 3l5.5 5.5h-5.5z"/><circle cx="16" cy="15.8" r="3.1"/><path d="M18.3 18.1l2.7 2.7"/>',
 check:'<path d="M4 12.5l5 5L20 6.5"/>',ok:'<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.8 2.8L16.2 9"/>',
 play:'<path d="M7 4.5v15l12-7.5z"/>',q:'<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',repo:'<path d="M6 3.5h11.5v14H7.5A1.5 1.5 0 0 0 6 19v-15.5zM6 19a1.5 1.5 0 0 0 1.5 1.5h10"/>',
 car:'<path d="M3 4.5l3 3 3-3"/>',burger:'<path d="M4 8h16M4 16h16"/>'
};
function svg(n,vb){return '<svg viewBox="'+(vb||"0 0 24 24")+'" aria-hidden="true">'+I[n]+"</svg>"}
function tile(n){return '<span class="sn-tile t-'+n+'">'+svg(n)+"</span>"}
function it(href,icon,t,s,tag,id){return '<a class="sn-it" href="'+href+'"'+(id?' id="'+id+'"':"")+">"+svg(icon)+"<b>"+t+"</b>"+(tag?"<i"+(tag.ok?' class="ok"':"")+">"+(tag.t||"")+"</i>":"")+"<small>"+s+"</small></a>"}
var T=BASE+"doc-test/",A=BASE+"doc-audit/";
var GH='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 .8a7.2 7.2 0 0 0-2.3 14c.4.1.5-.2.5-.4v-1.3c-2 .4-2.4-.9-2.4-.9-.3-.8-.8-1.1-.8-1.1-.7-.5 0-.5 0-.5.7.1 1.1.8 1.1.8.7 1.1 1.7.8 2.1.6.1-.5.3-.8.5-1-1.6-.2-3.3-.8-3.3-3.6 0-.8.3-1.4.7-1.9-.1-.2-.3-.9.1-1.9 0 0 .6-.2 2 .7a6.8 6.8 0 0 1 3.6 0c1.4-.9 2-.7 2-.7.4 1 .1 1.7.1 1.9.5.5.7 1.1.7 1.9 0 2.8-1.7 3.4-3.3 3.6.3.2.5.7.5 1.4v2.1c0 .2.1.5.5.4A7.2 7.2 0 0 0 8 .8z"/></svg>';
var LOGO='<svg viewBox="0 0 64 64" aria-hidden="true"><rect x="2" y="2" width="60" height="60" rx="15" fill="#0A66D6"/><path d="M21 22l13 10-13 10" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><rect x="38" y="39" width="12" height="5.5" rx="2.75" fill="#fff"/></svg>';
function app(k,label){return '<button type="button" class="sn-app" id="sn-b-'+k+'" aria-expanded="false" aria-controls="sn-m-'+k+'"'+(CUR===k?' aria-current="page"':"")+">"+tile(k)+"<b>"+label+"</b>"+svg("car","0 0 12 12").replace("<svg",'<svg class="sn-car"')+"</button>"}
var links=[["How it works","#steps"],["Proof","#proof"],["Tools","#tools"],["Plan","#plan"]];
host.innerHTML='<nav class="sn" aria-label="Site"><div class="sn-bar">'+
 '<a class="sn-wm" href="'+BASE+'" aria-label="FirstRun home">'+LOGO+"<span>FirstRun</span></a>"+
 app("test","Doc-test")+app("audit","Doc-audit")+'<span class="sn-sep" aria-hidden="true"></span>'+
 links.map(function(l){return '<a class="sn-lk" href="'+BASE+l[1]+'">'+l[0]+"</a>"}).join("")+
 '<span class="sn-sp"></span><a class="sn-gh" href="https://github.com/HighnessAtharva/firstrun" aria-label="FirstRun on GitHub">'+GH+"</a>"+
 '<button type="button" class="sn-burger" id="sn-b-more" aria-label="More links" aria-expanded="false" aria-controls="sn-m-more">'+svg("burger")+"</button></div>"+
 '<div class="sn-mm mm-test" id="sn-m-test" role="region" aria-label="Doc-test">'+
  '<div class="sn-hero">'+tile("test")+"<h3>Doc-test</h3><p>Runs a docs quickstart in a clean container, fixes the step that breaks, and proves the fix in a second clean run.</p>"+
  '<div class="sn-nums"><span><b id="sn-n-fix">&nbsp;</b>fixes proven</span><span><b id="sn-n-ok">&nbsp;</b>pages that work</span></div>'+
  '<a class="sn-go" href="'+T+'">Open doc-test</a></div>'+
  '<div class="sn-list"><div class="sn-h">Results</div>'+
  it(T+"?f=fixed","check","Fix proven","Docs bugs with a fix that passed a clean rerun",{t:"",ok:1},"sn-c-fix")+
  it(T+"?f=works","ok","Docs that work","Every step passed as written",{t:""},"sn-c-ok")+
  it(T+"?f=open","q","Inconclusive","Runs that stopped before a fix was proven",{t:""},"sn-c-q")+
  '<div class="sn-h">Watch one</div>'+
  it(T+"#ex=dbt","play","Replay the dbt run","A docs bug, the fix, the clean rerun, the PR")+"</div></div>"+
 '<div class="sn-mm mm-audit" id="sn-m-audit" role="region" aria-label="Doc-audit">'+
  '<div class="sn-hero">'+tile("audit")+"<h3>Doc-audit</h3><p>Reads a repo's git history and lists the docs pages the code changed underneath, plus shipped features with no docs.</p>"+
  '<div class="sn-nums"><span><b id="sn-n-aud">&nbsp;</b>repos audited</span><span><b id="sn-n-stale">&nbsp;</b>stale pages found</span></div>'+
  '<a class="sn-go" href="'+A+'">Open doc-audit</a></div>'+
  '<div class="sn-list"><div class="sn-h">Real audits</div><div id="sn-aud"></div>'+
  it(A+"#start","plus","Audit your repo","Get the one-line command")+"</div></div>"+
 '<div class="sn-mm mm-more" id="sn-m-more" role="region" aria-label="More"><div class="sn-list">'+
  it(T,"test","Doc-test","Run a quickstart, fix it, prove it")+it(A,"audit","Doc-audit","Find the docs your code outgrew")+
  '<div class="sn-h">FirstRun</div>'+links.map(function(l){return it(BASE+l[1],"repo",l[0],"On the home page")}).join("")+
  it("https://github.com/HighnessAtharva/firstrun","repo","GitHub","The public repo")+"</div></div></nav>";

var $=function(i){return document.getElementById(i)},open=null,timer;
function set(k,on){
 var b=$("sn-b-"+k),m=$("sn-m-"+k);if(!b||!m)return;
 if(on&&open&&open!==k)set(open,false);
 b.setAttribute("aria-expanded",on?"true":"false");m.classList.toggle("on",on);open=on?k:(open===k?null:open);
 if(on)load();
}
["test","audit","more"].forEach(function(k){
 var b=$("sn-b-"+k),m=$("sn-m-"+k);
 b.addEventListener("click",function(e){e.stopPropagation();set(k,b.getAttribute("aria-expanded")!=="true")});
 if(k!=="more"&&matchMedia("(hover:hover) and (pointer:fine)").matches){
  [b,m].forEach(function(x){
   x.addEventListener("mouseenter",function(){clearTimeout(timer);timer=setTimeout(function(){set(k,true)},open?0:120)});
   x.addEventListener("mouseleave",function(){clearTimeout(timer);timer=setTimeout(function(){if(open===k)set(k,false)},220)});
  });
 }
});
document.addEventListener("click",function(e){if(open&&!host.contains(e.target))set(open,false)});
document.addEventListener("keydown",function(e){if(e.key==="Escape"&&open){var k=open;set(k,false);$("sn-b-"+k).focus()}});
window.addEventListener("hashchange",function(){if(open)set(open,false)});
host.addEventListener("click",function(e){if(open&&e.target.closest(".sn-mm a"))set(open,false)});

/* live numbers, loaded once on first open or when idle */
var loaded=false;
function verdict(r){return r.status==="verified"&&r.fixes>0?"fixed":(r.status==="passed"||r.status==="verified")?"works":"open"}
function load(){
 if(loaded)return;loaded=true;
 fetch(BASE+"runs/index.json").then(function(r){return r.json()}).then(function(j){
  var by={};(j.runs||[]).filter(function(r){return!r.fixture}).forEach(function(r){var k=(r.url||r.target).replace(/[#?].*$/,"").replace(/\/$/,"");(by[k]=by[k]||[]).push(verdict(r))});
  var c={fixed:0,works:0,open:0};
  Object.keys(by).forEach(function(k){var v=by[k];c[v.indexOf("fixed")>=0?"fixed":v.indexOf("works")>=0?"works":"open"]++});
  $("sn-n-fix").textContent=c.fixed;$("sn-n-ok").textContent=c.works;
  $("sn-c-fix").querySelector("i").textContent=c.fixed;$("sn-c-ok").querySelector("i").textContent=c.works;$("sn-c-q").querySelector("i").textContent=c.open;
 }).catch(function(){});
 fetch(BASE+"audits/index.json").then(function(r){return r.json()}).then(function(j){
  var a=(j.audits||[]),st=0;a.forEach(function(x){st+=+x.stale||0});
  $("sn-n-aud").textContent=a.length;$("sn-n-stale").textContent=st;
  $("sn-aud").innerHTML=a.slice(0,4).map(function(x){var r=String(x.repo).replace(/[<>&"]/g,"");return it(A+"?id="+encodeURIComponent(x.id),"repo",r,(+x.pages||0)+" pages, "+(+x.uncovered||0)+" features with no docs",{t:(+x.stale||0)+" stale"})}).join("");
 }).catch(function(){});
}
if("requestIdleCallback" in window)requestIdleCallback(load,{timeout:2500});else setTimeout(load,1500);
})();
