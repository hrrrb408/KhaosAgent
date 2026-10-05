import Darwin
import Foundation

enum KernelCStringArray {
    static func create(_ values: [String]) throws -> [UnsafeMutablePointer<CChar>?] {
        var result: [UnsafeMutablePointer<CChar>?] = []
        for value in values {
            guard let pointer = value.withCString({ strdup($0) }) else {
                release(result)
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(ENOMEM))
            }
            result.append(pointer)
        }
        result.append(nil)
        return result
    }

    static func release(_ values: [UnsafeMutablePointer<CChar>?]) {
        for value in values {
            if let value { free(value) }
        }
    }
}
