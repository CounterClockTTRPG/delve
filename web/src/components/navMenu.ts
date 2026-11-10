import { createContext, useContext } from "react";

/** Whether the phone's whole nav is open as a sheet (DEL-188): the bar's More opens it, and so does the play screen's
 * Menu, where the bar itself is hidden. Null where there is no nav: a seat's shell. */
export interface NavMenu {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export const NavMenuContext = createContext<NavMenu | null>(null);

export function useNavMenu(): NavMenu | null {
  return useContext(NavMenuContext);
}
