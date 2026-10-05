import Foundation

@objc protocol XPCPeerIdentityProbe {
    func peerIdentity(withReply reply: @escaping (String) -> Void)
}
