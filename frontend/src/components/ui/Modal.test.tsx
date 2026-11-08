import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Modal } from "./Modal";

afterEach(cleanup);

function Form() {
  const [title, setTitle] = useState("");
  return (
    // onClose est recréé à chaque rendu, comme dans les vraies pages.
    <Modal open title="T" onClose={() => undefined}>
      <button type="button">premier</button>
      <input
        aria-label="titre"
        value={title}
        onChange={(e) => {
          setTitle(e.target.value);
        }}
      />
      <button type="button">dernier</button>
    </Modal>
  );
}

describe("Modal", () => {
  it("keeps focus on the field being typed in", () => {
    render(<Form />);
    const input = screen.getByLabelText("titre");
    input.focus();
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.change(input, { target: { value: "ab" } });
    expect(document.activeElement).toBe(input);
  });

  it("keeps Tab inside the dialog", () => {
    render(<Form />);
    const last = screen.getByText("dernier");
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByText("premier"));
  });

  it("gives focus back to what opened it", () => {
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button
            type="button"
            onClick={() => {
              setOpen(true);
            }}
          >
            ouvrir
          </button>
          <Modal
            open={open}
            title="T"
            onClose={() => {
              setOpen(false);
            }}
          >
            <button type="button">dedans</button>
          </Modal>
        </>
      );
    }
    render(<Host />);
    const opener = screen.getByText("ouvrir");
    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByText("dedans"));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.activeElement).toBe(opener);
  });
});
