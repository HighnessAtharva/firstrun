/* One floating island nav for every page. Usage:
   <div id="sitenav"></div><script src="<base>assets/site-nav.js" data-cur="test|audit|plan|home" defer></script>
   Over any element marked data-nav="dark" the bar turns dark, so it reads on a dark hero. */
(function(){
"use strict";
var me=document.currentScript||document.querySelector('script[src*="site-nav.js"]');
var BASE=me.src.replace(/assets\/site-nav\.js.*$/,""),CUR=me.getAttribute("data-cur")||"home",HOME=CUR==="home";
var host=document.getElementById("sitenav");
if(!host){host=document.createElement("div");host.id="sitenav";document.body.insertBefore(host,document.body.firstChild)}
var I={
 test:'<rect x="2.5" y="3.5" width="19" height="17" rx="3.5"/><path d="M6.8 9.2l3 2.6-3 2.6M12.3 15.6h4.9"/>',
 audit:'<path d="M12.5 3H7a2.5 2.5 0 0 0-2.5 2.5v13A2.5 2.5 0 0 0 7 21h4.2"/><path d="M12.5 3l5.5 5.5h-5.5z"/><circle cx="16" cy="15.8" r="3.1"/><path d="M18.3 18.1l2.7 2.7"/>',
 check:'<path d="M4 12.5l5 5L20 6.5"/>',ok:'<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.8 2.8L16.2 9"/>',
 play:'<path d="M7 4.5v15l12-7.5z"/>',q:'<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',repo:'<path d="M6 3.5h11.5v14H7.5A1.5 1.5 0 0 0 6 19v-15.5zM6 19a1.5 1.5 0 0 0 1.5 1.5h10"/>',
 rcpt:'<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',watch:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10.5 9.5v5l4-2.5z"/>',
 cmp:'<path d="M4 6h16M4 12h16M4 18h16"/><path d="M9 4v16"/>',plan:'<path d="M4 19V9M10 19V5M16 19v-7M21 19H3"/>',
 car:'<path d="M3 4.5l3 3 3-3"/>',burger:'<path d="M4 8h16M4 16h16"/>',x:'<path d="M6 6l12 12M18 6L6 18"/>'
};
function svg(n,vb,cls){return '<svg'+(cls?' class="'+cls+'"':"")+' viewBox="'+(vb||"0 0 24 24")+'" aria-hidden="true">'+I[n]+"</svg>"}
function tile(n){return '<span class="sn-tile t-'+n+'">'+svg(n)+"</span>"}
function it(href,icon,t,s,tag,id){return '<a class="sn-it" href="'+href+'"'+(id?' id="'+id+'"':"")+">"+svg(icon)+"<b>"+t+"</b>"+(tag?"<i"+(tag.ok?' class="ok"':"")+">"+(tag.t||"")+"</i>":"")+"<small>"+s+"</small></a>"}
var T=BASE+"doc-test/",A=BASE+"doc-audit/";
var GH='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 .8a7.2 7.2 0 0 0-2.3 14c.4.1.5-.2.5-.4v-1.3c-2 .4-2.4-.9-2.4-.9-.3-.8-.8-1.1-.8-1.1-.7-.5 0-.5 0-.5.7.1 1.1.8 1.1.8.7 1.1 1.7.8 2.1.6.1-.5.3-.8.5-1-1.6-.2-3.3-.8-3.3-3.6 0-.8.3-1.4.7-1.9-.1-.2-.3-.9.1-1.9 0 0 .6-.2 2 .7a6.8 6.8 0 0 1 3.6 0c1.4-.9 2-.7 2-.7.4 1 .1 1.7.1 1.9.5.5.7 1.1.7 1.9 0 2.8-1.7 3.4-3.3 3.6.3.2.5.7.5 1.4v2.1c0 .2.1.5.5.4A7.2 7.2 0 0 0 8 .8z"/></svg>';
var LOGO='<svg viewBox="0 0 64 64" aria-hidden="true"><rect x="2" y="2" width="60" height="60" rx="15" fill="#0A66D6"/><path d="M21 22l13 10-13 10" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><rect x="38" y="39" width="12" height="5.5" rx="2.75" fill="#fff"/></svg>';
function app(k,label){return '<button type="button" class="sn-app a-'+k+'" id="sn-b-'+k+'" aria-expanded="false" aria-controls="sn-m-'+k+'"'+(CUR===k?' aria-current="page"':"")+">"+tile(k)+"<b>"+label+"</b>"+svg("car","0 0 12 12","sn-car")+"</button>"}
/* the section links name what is on the home page, in page order. [label, target, icon, subtitle] */
var links=[["Receipts","#receipt","rcpt","What a run cost, and the proof"],["Watch","#watch","watch","Three short demos"],["Compare","#compare","cmp","FirstRun next to the usual tools"],["Plan","plan/","plan","What each plan may spend"]];
function href(l){return l[1].charAt(0)==="#"?(HOME?l[1]:BASE+l[1]):BASE+l[1]}
function curLink(l){return CUR==="plan"&&l[1]==="plan/"}
host.innerHTML='<nav class="sn-nav" aria-label="Site"><div class="sn-bar">'+
 '<a class="sn-wm" href="'+BASE+'" aria-label="FirstRun home"'+(HOME?' aria-current="page"':"")+">"+LOGO+"<span>FirstRun</span></a>"+
 '<span class="sn-apps">'+app("test","Doc-test")+app("audit","Doc-audit")+"</span>"+
 '<span class="sn-sep" aria-hidden="true"></span><span class="sn-links">'+
 links.map(function(l){return '<a class="sn-lk" data-k="'+l[1]+'" href="'+href(l)+'"'+(curLink(l)?' aria-current="page"':"")+'>'+l[0]+"</a>"}).join("")+
 '</span><span class="sn-sp"></span><a class="sn-gh" href="https://github.com/HighnessAtharva/firstrun" aria-label="FirstRun on GitHub">'+GH+"</a>"+
 '<a class="sn-try" id="sn-try" href="'+BASE+'#hero">Try it</a>'+
 '<button type="button" class="sn-burger" id="sn-b-more" aria-label="Menu" aria-expanded="false" aria-controls="sn-m-more">'+svg("burger","0 0 24 24","sn-ib")+svg("x","0 0 24 24","sn-ix")+"</button></div>"+
 '<div class="sn-mm mm-test" id="sn-m-test" role="region" aria-label="Doc-test">'+
  '<div class="sn-hero">'+tile("test")+"<h3>Doc-test</h3><p>Runs a docs quickstart in a clean container, fixes the step that breaks, and proves the fix in a second clean run.</p>"+
  '<div class="sn-nums"><span><b id="sn-n-fix">&nbsp;</b>fixes proven</span><span><b id="sn-n-ok">&nbsp;</b>pages that work</span></div>'+
  '<a class="sn-go" href="'+T+'">Open Doc-test</a></div>'+
  '<div class="sn-list"><div class="sn-h">Results</div>'+
  it(T+"?f=fixed","check","Fix proven","Docs bugs with a fix that passed a clean rerun",{t:"",ok:1},"sn-c-fix")+
  it(T+"?f=works","ok","Docs that work","Every step passed as written",{t:""},"sn-c-ok")+
  it(T+"?f=open","q","Inconclusive","Runs that stopped before a fix was proven",{t:""},"sn-c-q")+
  '<div class="sn-h">Watch one</div>'+
  it(T+"#ex=dbt","play","Replay the dbt run","A docs bug, the fix, the clean rerun, the PR")+"</div></div>"+
 '<div class="sn-mm mm-audit" id="sn-m-audit" role="region" aria-label="Doc-audit">'+
  '<div class="sn-hero">'+tile("audit")+"<h3>Doc-audit</h3><p>Reads a repo's git history and lists the docs pages the code changed underneath, plus shipped features with no docs.</p>"+
  '<div class="sn-nums"><span><b id="sn-n-aud">&nbsp;</b>repos audited</span><span><b id="sn-n-stale">&nbsp;</b>stale pages found</span></div>'+
  '<a class="sn-go" href="'+A+'">Open Doc-audit</a></div>'+
  '<div class="sn-list"><div class="sn-h">Real audits</div><div id="sn-aud"></div>'+
  it(A+"#start","plus","Audit your repo","Paste a GitHub repo")+"</div></div>"+
 '<div class="sn-mm mm-more" id="sn-m-more" role="region" aria-label="Menu"><div class="sn-list">'+
  '<div class="sn-h">The two tools</div>'+
  '<a class="sn-big b-test" href="'+T+'"'+(CUR==="test"?' aria-current="page"':"")+">"+tile("test")+"<b>Doc-test</b><small>Run a quickstart, fix it, prove it</small></a>"+
  '<a class="sn-big b-audit" href="'+A+'"'+(CUR==="audit"?' aria-current="page"':"")+">"+tile("audit")+"<b>Doc-audit</b><small>Find the docs your code outgrew</small></a>"+
  '<div class="sn-h">On this site</div>'+links.map(function(l){return it(href(l),l[2],l[0],l[3])}).join("")+
  it("https://github.com/HighnessAtharva/firstrun","repo","GitHub","The public repo")+"</div></div></nav>";

var $=function(i){return document.getElementById(i)},nav=host.firstChild,open=null,timer;
function set(k,on){
 var b=$("sn-b-"+k),m=$("sn-m-"+k);if(!b||!m)return;
 if(on&&open&&open!==k)set(open,false);
 b.setAttribute("aria-expanded",on?"true":"false");m.classList.toggle("on",on);open=on?k:(open===k?null:open);
 nav.classList.toggle("sn-open",!!open);
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

/* Try it: put the cursor in this page's own input when it has one, else go to the home page box */
$("sn-try").addEventListener("click",function(e){
 var ids=["u","goU","repo"];
 for(var i=0;i<ids.length;i++){var x=$(ids[i]);if(x&&x.offsetParent){e.preventDefault();
  var rm=matchMedia("(prefers-reduced-motion:reduce)").matches;
  x.scrollIntoView({behavior:rm?"auto":"smooth",block:ids[i]==="u"?"center":"center"});
  setTimeout(function(){x.focus({preventScroll:true})},rm?0:420);if(open)set(open,false);return}}
});

/* dark bar over a dark section: watch a thin strip at the top of the viewport */
if("IntersectionObserver" in window){
 var darks=document.querySelectorAll('[data-nav="dark"]'),on={};
 if(darks.length){
  var io=new IntersectionObserver(function(en){en.forEach(function(e){on[e.target.id||"x"]=e.isIntersecting});
   var any=false;for(var k in on)if(on[k])any=true;nav.classList.toggle("dark",any)},{rootMargin:"0px 0px -92% 0px"});
  Array.prototype.forEach.call(darks,function(d){io.observe(d)});
 }
 /* home page: mark the part of the page you are reading */
 if(HOME){
  var spy={steps:"sn-b-test",audit:"sn-b-audit",receipt:"#receipt",watch:"#watch",compare:"#compare"};
  var els=[];Object.keys(spy).forEach(function(id){var s=$(id);if(s)els.push(s)});
  var here=null;
  var so=new IntersectionObserver(function(en){en.forEach(function(e){
    var t=spy[e.target.id],el=t.charAt(0)==="#"?nav.querySelector('.sn-lk[data-k="'+t+'"]'):$(t);if(!el)return;
    if(e.isIntersecting){if(here&&here!==el)here.classList.remove("is-here");el.classList.add("is-here");here=el}
    else if(here===el){el.classList.remove("is-here");here=null}
   })},{rootMargin:"-45% 0px -50% 0px"});
  els.forEach(function(s){so.observe(s)});
 }
}

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
