import { landscape } from "./landscape";
import { portrait } from "./portrait";
import { Layout } from "./types";

export * from "./types";
export { landscape, portrait };
export * from "./diagramMetrics";

/** Pick the layout for the active canvas (portrait when taller than wide). */
export const getLayout = (width: number, height: number): Layout => (height > width ? portrait : landscape);
