import Foundation

/// Date parsing/formatting shared across list rows and the reader.
///
/// The BFF emits ISO-8601 instants with `timespec="seconds"` (no
/// fractional part) but upstream values occasionally carry millis or
/// microseconds; accept the common variants.
enum LumiDate {
    private static let isoSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let isoFractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    static func parse(_ string: String?) -> Date? {
        guard let string, !string.isEmpty else { return nil }
        if let date = isoFractional.date(from: string) { return date }
        if let date = isoSeconds.date(from: string) { return date }
        return nil
    }

    /// Short list timestamp: today → `HH:mm`, this year → `M-d`, older → `yyyy-M-d`.
    static func listLabel(_ date: Date?, relativeTo now: Date = Date()) -> String {
        guard let date else { return "" }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        if calendar.isDate(date, inSameDayAs: now) {
            return timeFormatter.string(from: date)
        }
        let nowYear = calendar.component(.year, from: now)
        if calendar.component(.year, from: date) == nowYear {
            return sameYearFormatter.string(from: date)
        }
        return fullDateFormatter.string(from: date)
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .none
        formatter.timeStyle = .short
        return formatter
    }()

    private static let sameYearFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.setLocalizedDateFormatFromTemplate("Md")
        return formatter
    }()

    private static let fullDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.setLocalizedDateFormatFromTemplate("yMd")
        return formatter
    }()

    static let fullFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter
    }()
}
