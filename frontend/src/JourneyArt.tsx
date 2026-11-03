import {t,useLocale} from './i18n';
/** Decorative images stay separate from the machine and device controls. */
export function JourneyArt(){
  useLocale();
  return <div className="journey-art" aria-hidden="true">
    <div className="journey-caption"><span>FLOWERS & MAGIC</span><h2>{t("花语旅途","Floral journey")}</h2><p>{t("在等待的片刻，继续旅程。","Continue the journey while you wait.")}</p></div>
    <div className="journey-portraits" aria-hidden="true">
      <div className="journey-orbit"/>
      <div className="journey-flower flower-one">✦</div><div className="journey-flower flower-two">✧</div>
      <div className="journey-character journey-frieren"><img src="/themes/journey/frieren.png" alt="" width="750" height="683" draggable={false}/></div>
      <div className="journey-character journey-fern"><img src="/themes/journey/fern.png" alt="" width="750" height="683" draggable={false}/></div>
    </div>
    <div className="journey-names"><span>{t("芙莉莲","Frieren")}<small>FRIEREN</small></span><i>✧</i><span>{t("菲伦","Fern")}<small>FERN</small></span></div>
    <span className="journey-credit">{t("角色立绘 · 动画官网","Character artwork · Official anime website")}</span>
  </div>;
}
