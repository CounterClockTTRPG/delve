import { useQuery } from "@tanstack/react-query";
import { accountKeys, getMe } from "./api";

/** Who this browser is: the owner, an account, or a seat at one table (which may read nothing but its table). Read
 * once: who this is changes only with a new page, and an answer that failed isn't asked again by each screen. One
 * query for the whole app (`accountKeys.me()`), which logging in or out, and keeping a seat, invalidate. */
export function useMe() {
  return useQuery({ queryKey: accountKeys.me(), queryFn: () => getMe(), staleTime: Infinity, retryOnMount: false });
}
