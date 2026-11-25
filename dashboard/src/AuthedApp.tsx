import { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { Nav } from "./components/Nav";
import { Containment } from "./pages/Containment";
import { LabMonitor } from "./pages/LabMonitor";
import { LabTapes } from "./pages/LabTapes";
import { parseHash, type Route } from "./routes";

function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

function PageView({ route }: { route: Route }) {
  switch (route.page) {
    case "tapes":
      return <LabTapes tapeId={route.tapeId} />;
    case "containment":
      return <Containment />;
    default:
      return <LabMonitor />;
  }
}
export function AuthedApp() {
  const route = useRoute();
  return (
    <>
      <Header />
      <div className="page">
        <Nav current={route.page} />
        <main>
          <PageView route={route} />
        </main>
      </div>
    </>
  );
}
