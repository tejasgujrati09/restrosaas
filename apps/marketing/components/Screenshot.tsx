import Image from "next/image";

/**
 * A real product screenshot with a required caption, in a light "window" frame. Width/height
 * are the screenshot's actual pixel dimensions so next/image can reserve space (no CLS).
 * `phone` frames a portrait guest-screen capture like the hero's phone mockup.
 */
export function Screenshot({
  src,
  alt,
  caption,
  width,
  height,
  priority,
  phone,
}: {
  src: string;
  alt: string;
  caption: string;
  width: number;
  height: number;
  priority?: boolean;
  phone?: boolean;
}) {
  return (
    <figure className={`shot${phone ? " shot-phone" : ""}`}>
      <div className="shot-frame">
        <Image
          src={src}
          alt={alt}
          width={width}
          height={height}
          priority={priority}
          sizes={phone ? "(min-width: 900px) 330px, 80vw" : "(min-width: 1180px) 620px, (min-width: 900px) 55vw, 100vw"}
        />
      </div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}
