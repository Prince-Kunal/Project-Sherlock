import { Hero } from "@/components/landing/hero";
import { LandingNav } from "@/components/landing/landing-nav";
import {
  Bento,
  Closing,
  Footer,
  Manifesto,
  Method,
  OpenOutreach,
  Rules,
  Sources,
} from "@/components/landing/sections";
import { SmoothScroll } from "@/components/landing/smooth-scroll";

export default function LandingPage() {
  return (
    <SmoothScroll>
      <div className="grain flex min-h-[100dvh] flex-col">
        <LandingNav />
        <main id="main">
          <Hero />
          <Sources />
          <Method />
          <Bento />
          <OpenOutreach />
          <Manifesto />
          <Rules />
          <Closing />
        </main>
        <Footer />
      </div>
    </SmoothScroll>
  );
}
