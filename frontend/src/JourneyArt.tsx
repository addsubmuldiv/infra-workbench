/** Decorative images stay separate from the machine and device controls. */
export function JourneyArt(){
  return <div className="journey-art" aria-hidden="true">
    <div className="journey-caption"><span>FLOWERS & MAGIC</span><h2>花语旅途</h2><p>在等待的片刻，继续旅程。</p></div>
    <div className="journey-portraits" aria-hidden="true">
      <div className="journey-orbit"/>
      <div className="journey-flower flower-one">✦</div><div className="journey-flower flower-two">✧</div>
      <div className="journey-character journey-frieren"><img src="/themes/journey/frieren.png" alt="" width="750" height="683" draggable={false}/></div>
      <div className="journey-character journey-fern"><img src="/themes/journey/fern.png" alt="" width="750" height="683" draggable={false}/></div>
    </div>
    <div className="journey-names"><span>芙莉莲<small>FRIEREN</small></span><i>✧</i><span>菲伦<small>FERN</small></span></div>
    <span className="journey-credit">角色立绘 · 动画官网</span>
  </div>;
}
