import { createRoot } from "react-dom/client";
import App from "./StudioApp";
import "./styles.css";
import "./motion.css";
import "./engine.css";
import "./usage.css";
import "./a11y.css";
import "./rail.css";

createRoot(document.getElementById("root")!).render(<App />);
