import { NextResponse } from "next/server";
import { z } from "zod";
import { resolveTelegramRoute, sendTelegramMessage } from "@/lib/telegram";
import { sendGuestEmail } from "@/lib/email";

const BookingSchema = z.object({
  propertyCode: z.string().min(3),
  roomId: z.string().min(1),
  guestName: z.string().min(2),
  phone: z.string().min(6),
  email: z.string().email(),
  checkIn: z.string().min(8),
  checkOut: z.string().min(8),
  note: z.string().optional().default("")
});

export async function POST(req) {
  try {
    const body = await req.json();
    const data = BookingSchema.parse(body);

    const route = resolveTelegramRoute(data.propertyCode);
    const msg = [
      `<b>NEW BOOKING REQUEST</b>`,
      `<b>Property:</b> ${data.propertyCode}`,
      `<b>Room:</b> ${data.roomId}`,
      `<b>Name:</b> ${data.guestName}`,
      `<b>Phone:</b> ${data.phone}`,
      `<b>Email:</b> ${data.email}`,
      `<b>Dates:</b> ${data.checkIn} → ${data.checkOut}`,
      data.note ? `<b>Note:</b> ${data.note}` : ''
    ].filter(Boolean).join("
");

    await sendTelegramMessage(route, msg);
    await sendGuestEmail({
      to: data.email,
      guestName: data.guestName,
      propertyCode: data.propertyCode,
      roomId: data.roomId,
      checkIn: data.checkIn,
      checkOut: data.checkOut
    });

    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error(e);
    return NextResponse.json({ ok: false, error: String(e?.message || e) }, { status: 400 });
  }
}
