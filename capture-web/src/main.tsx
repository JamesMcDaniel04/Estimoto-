import { createRoot } from "react-dom/client";
import { CaptureApp } from "./CaptureApp";
import { CaptureRPC } from "./rpc";
import "./style.css";

const target = document.getElementById("root");
if (target) createRoot(target).render(<CaptureApp rpc={new CaptureRPC()} />);
