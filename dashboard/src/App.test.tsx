import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  beforeEach(() => sessionStorage.clear());

  it("shows only the login screen when no token is stored", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Haunted Honeypot");
    expect(screen.getByLabelText("API token")).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
