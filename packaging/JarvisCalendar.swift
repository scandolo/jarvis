import EventKit
import Foundation


/// Write-only EventKit adapter. The user must confirm the event before this is called.
final class JarvisCalendar {
    private let store = EKEventStore()

    func create(
        title: String, start: String, durationMinutes: Int,
        completion: @escaping ([String: Any]) -> Void
    ) {
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              title.count <= 120,
              [30, 60, 90, 120].contains(durationMinutes),
              let date = ISO8601DateFormatter().date(from: start),
              date > Date(), date < Date().addingTimeInterval(91 * 24 * 3600)
        else {
            completion(["ok": false, "error": "Invalid event details"])
            return
        }
        let save = { [weak self] (granted: Bool, error: Error?) in
            guard let self = self else { return }
            guard granted else {
                completion(["ok": false, "error": error?.localizedDescription
                    ?? "Calendar write access was not granted"])
                return
            }
            guard let calendar = self.store.defaultCalendarForNewEvents else {
                completion(["ok": false, "error": "No writable default calendar is available"])
                return
            }
            let event = EKEvent(eventStore: self.store)
            event.title = title
            event.startDate = date
            event.endDate = date.addingTimeInterval(TimeInterval(durationMinutes * 60))
            event.calendar = calendar
            do {
                try self.store.save(event, span: .thisEvent, commit: true)
                completion(["ok": true, "summary": "added \(title) to Calendar"])
            } catch {
                completion(["ok": false, "error": error.localizedDescription])
            }
        }
        if #available(macOS 14.0, *) {
            store.requestWriteOnlyAccessToEvents(completion: save)
        } else {
            store.requestAccess(to: .event, completion: save)
        }
    }
}
