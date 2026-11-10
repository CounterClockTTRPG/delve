import Lightbox from "../components/Lightbox";

/**
 * A campaign's painted banner, in a frame that takes the look's `--card-edge`. `campaign` is the campaign page's (full
 * width, 21:9) and `thumb` the module page's (12rem wide); the picture covers its frame.
 */
export default function Banner({ src, alt, variant }: { src: string; alt: string; variant: "campaign" | "thumb" }) {
  // The campaign page's banner enlarges on a click (DEL-234); the module page's small one is a link to its campaign.
  if (variant === "campaign") {
    return (
      <div className="banner banner-campaign">
        <Lightbox label={alt} title={alt} big={<img className="lightbox-image" src={src} alt={alt} />} className="banner-enlarge">
          <img src={src} alt={alt} />
        </Lightbox>
      </div>
    );
  }
  return (
    <div className={`banner banner-${variant}`}>
      <img src={src} alt={alt} />
    </div>
  );
}
