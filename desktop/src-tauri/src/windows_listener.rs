//! Windows loopback connection refusal can outlast HTTP deadlines. Query the
//! OS listener table instead; errors stay unknown rather than proving absence.
use std::{mem::{offset_of, size_of}, net::{Ipv4Addr, SocketAddr}};
use windows_sys::Win32::{
    Foundation::{ERROR_INSUFFICIENT_BUFFER, NO_ERROR},
    NetworkManagement::IpHelper::{GetExtendedTcpTable, MIB_TCPROW_OWNER_PID, MIB_TCP6ROW_OWNER_PID,
        MIB_TCPTABLE_OWNER_PID, MIB_TCP6TABLE_OWNER_PID, TCP_TABLE_OWNER_PID_LISTENER},
    Networking::WinSock::{AF_INET, AF_INET6},
};

// T is one of the two SDK row structs below (only integer/byte-array fields).
fn rows<T: Copy>(family: u32, offset: usize) -> Result<Vec<T>, String> {
    let mut bytes = 0u32;
    let first = unsafe { GetExtendedTcpTable(std::ptr::null_mut(), &mut bytes, 0, family, TCP_TABLE_OWNER_PID_LISTENER, 0) };
    if first != ERROR_INSUFFICIENT_BUFFER && first != NO_ERROR {
        return Err(format!("无法查询本地后台端口：Windows error {first}。未停止任何进程。"));
    }
    loop {
        // DWORD alignment meets the SDK table alignment. read_unaligned below
        // also avoids creating a Rust reference into a variable-length C table.
        let mut buffer = vec![0u32; (bytes as usize).div_ceil(size_of::<u32>()).max(1)];
        let result = unsafe { GetExtendedTcpTable(buffer.as_mut_ptr().cast(), &mut bytes, 0, family, TCP_TABLE_OWNER_PID_LISTENER, 0) };
        if result == ERROR_INSUFFICIENT_BUFFER { continue; }
        if result != NO_ERROR {
            return Err(format!("无法查询本地后台端口：Windows error {result}。未停止任何进程。"));
        }
        let count = buffer[0] as usize;
        let end = count.checked_mul(size_of::<T>()).and_then(|length| offset.checked_add(length));
        if bytes as usize > buffer.len()*size_of::<u32>() || end.is_none_or(|end| end > bytes as usize) {
            return Err("无法查询本地后台端口：Windows returned an invalid listener table。未停止任何进程。".into());
        }
        return Ok((0..count).map(|index| unsafe {
            std::ptr::read_unaligned(buffer.as_ptr().cast::<u8>().add(offset+index*size_of::<T>()).cast::<T>())
        }).collect());
    }
}

pub fn listening(address: SocketAddr) -> Result<bool, String> {
    let SocketAddr::V4(address) = address else {
        return Err("无法查询本地后台端口：expected IPv4 loopback。未停止任何进程。".into());
    };
    for row in rows::<MIB_TCPROW_OWNER_PID>(AF_INET as u32, offset_of!(MIB_TCPTABLE_OWNER_PID, table))? {
        let ip = Ipv4Addr::from(row.dwLocalAddr.to_ne_bytes());
        if u16::from_be(row.dwLocalPort as u16) == address.port() && (ip.is_unspecified() || ip == *address.ip()) {
            // The API is explicitly listener-only. Treat any matching row as
            // potentially occupied; HTTP still has to verify the workbench.
            return Ok(true);
        }
    }
    let mapped = address.ip().to_ipv6_mapped().octets();
    for row in rows::<MIB_TCP6ROW_OWNER_PID>(AF_INET6 as u32, offset_of!(MIB_TCP6TABLE_OWNER_PID, table))? {
        // The table does not expose IPV6_V6ONLY. :: might accept IPv4, so it
        // cannot safely prove absence. A failed HTTP check remains unknown.
        if u16::from_be(row.dwLocalPort as u16) == address.port() && (row.ucLocalAddr == [0;16] || row.ucLocalAddr == mapped) {
            return Ok(true);
        }
    }
    Ok(false)
}
