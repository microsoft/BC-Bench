# IsHandled Event Request Requirements

Applies to the `ishandled` subtype, in addition to the general and event-request requirements. Because this pattern lets subscribers bypass base logic, its evidence bar is higher.

## Requirements
- **Alternatives evaluated** — *Mandatory.* List the specific existing events or patterns already tried and precisely why each is insufficient. This cannot be waived.
- **Justification for bypass** — *Mandatory.* Give a specific technical reason why a standard event, a redesign, or a base-app contribution will not work. Avoid generic statements such as "we need IsHandled for our custom logic".
- **Performance impact** — *Mandatory (lightweight).* State the expected execution frequency and impact.
- **Data-sensitivity review** — *Mandatory (lightweight).* Confirm whether sensitive data is involved, or justify why access is necessary.
- **Multi-extension interaction** — *Mandatory (lightweight).* Acknowledge whether multiple subscribers could conflict and how the risk is contained.
- **Invocation example** — *Optional (recommended).* Show how the event is raised and provide a sample subscriber.
