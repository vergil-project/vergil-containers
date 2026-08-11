import { test, expect } from "vitest";

import { add, answer } from "./index";

test("add computes the answer", () => {
  expect(add(40, 2)).toBe(answer);
});
